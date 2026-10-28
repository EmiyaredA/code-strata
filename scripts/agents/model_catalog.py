"""Bounded model discovery with single-flight caching and shared shutdown."""
import copy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import threading
import time

from .adapters import BY_ID
from .config import validate_agent
from .models import COMMANDS, SOURCES, read_acp_models, read_claude_models, read_command_models
from .runtime import AgentError, Process, resolve_launch, redact
from .parameters import compact, select
from .defaults import codex_defaults, pi_defaults, opencode_defaults, config_signature
import re


class QueryCancellation:
    def __init__(self, stop, cancel=None):
        self.stop, self.cancel = stop, cancel

    def is_set(self):
        return self.stop.is_set() or bool(self.cancel and self.cancel.is_set())


class ModelCatalog:
    def __init__(self, node, stop, timeout=45):
        self.node, self.stop, self.timeout = node, stop, timeout
        self.condition = threading.Condition()
        self.slots = threading.BoundedSemaphore(2)
        self.cache, self.flights = {}, {}

    def _key(self, agent_id, launch):
        stamps = []
        for raw in launch["command"]:
            path = Path(raw)
            resolved = path.resolve()
            value = resolved.stat()
            stamps.append((str(path), str(resolved), value.st_mtime_ns, value.st_size))
        return agent_id, tuple(stamps), config_signature(agent_id, launch["env"])

    def get(self, body, cancel=None, timeout=None):
        if not isinstance(body, dict) or set(body) - {"agentId", "config", "force"}:
            raise ValueError("模型目录请求无效")
        agent_id, force = body.get("agentId"), body.get("force", False)
        if not isinstance(agent_id, str) or agent_id not in BY_ID or type(force) is not bool:
            raise ValueError("Agent 或刷新参数无效")
        config = validate_agent(body.get("config", {}), agent_id)
        cancellation = QueryCancellation(self.stop, cancel)
        started = time.monotonic()
        timeout = min(self.timeout, timeout) if timeout is not None else self.timeout
        result = {"agentId": agent_id, "models": [], "status": "error", "kind": None,
                  "message": "", "source": SOURCES[agent_id], "executablePath": None,
                  "fetchedAt": None, "cached": False}
        try:
            if cancellation.is_set():
                raise AgentError("cancelled", "服务正在关闭")
            launch = resolve_launch(BY_ID[agent_id], config, self.node)
            result["executablePath"] = launch["path"]
            key = self._key(agent_id, launch)
            if agent_id in ("dsh", "claude", "pi", "opencode"):
                key = (*key, config["model"])
        except (AgentError, OSError) as exc:
            return self._failed(result, exc)
        with self.condition:
            cached = self.cache.get(key)
            if not force and cached and time.monotonic() - cached[0] < 300:
                return {**copy.deepcopy(cached[1]), "cached": True}
            existing = self.flights.get(key)
            if existing is not None:
                while "result" not in existing:
                    if cancellation.is_set():
                        return self._failed(result, AgentError("cancelled", "服务正在关闭"))
                    if time.monotonic() - started >= timeout:
                        return self._failed(result, AgentError("timeout", "目录查询超时"))
                    self.condition.wait(.1)
                return copy.deepcopy(existing["result"])
            flight = {}
            self.flights[key] = flight
        try:
            result = self._query(agent_id, launch, result, started, config, cancellation, timeout)
        except Exception:
            # Fault isolation: malformed native metadata must not break Settings.
            result = self._failed(result, AgentError("protocol", "模型目录格式无法识别，可手动输入 ID"))
        finally:
            result["fetchedAt"] = datetime.now(timezone.utc).isoformat()
            with self.condition:
                if len(self.cache) >= 20:
                    self.cache.pop(next(iter(self.cache)))
                if result.get("kind") != "cancelled":
                    self.cache[key] = (time.monotonic(), copy.deepcopy(result))
                flight["result"] = copy.deepcopy(result)
                del self.flights[key]
                self.condition.notify_all()
        return result

    def _failed(self, result, exc):
        kind = exc.kind if isinstance(exc, AgentError) else "launch"
        status = "unsupported" if kind == "unsupported" else "unavailable" if kind in ("launch", "not_found", "auth") else "error"
        message = str(exc)
        if kind == "timeout":
            message = "模型目录查询超时，可刷新重试或手动输入 ID"
        elif kind == "cancelled":
            message = "模型目录查询已取消"
        elif message == "CLI 输出超过测试限制":
            message = "模型目录输出超过 8 MiB 限制，可手动输入 ID"
        elif message.startswith("CLI 调用失败"):
            message = "无法获取 CLI 模型目录，请检查配置后刷新，或手动输入 ID"
        return {**result, "status": status, "kind": kind, "message": redact(message),
                "fetchedAt": datetime.now(timezone.utc).isoformat()}

    def _query(self, agent_id, launch, result, started, config=None, cancellation=None, timeout=None):
        acquired, process = False, None
        cancellation = cancellation or self.stop
        timeout = self.timeout if timeout is None else timeout
        try:
            while not acquired:
                if cancellation.is_set():
                    raise AgentError("cancelled", "服务正在关闭")
                if time.monotonic() - started >= timeout:
                    raise AgentError("timeout", "目录查询超时")
                acquired = self.slots.acquire(timeout=.1)
            with tempfile.TemporaryDirectory(prefix="code-strata-models-") as cwd:
                try:
                    remaining = max(.01, timeout - (time.monotonic() - started))
                    config = config or {}
                    args = list(COMMANDS[agent_id])
                    if agent_id == "claude" and config.get("model"):
                        args.extend(["--model", config["model"]])
                    process = Process(launch, args, cwd, cancellation, remaining,
                                      max_output=8 * 1024 * 1024, max_line=8 * 1024 * 1024)
                    if agent_id == "dsh":
                        rows = read_acp_models(process, cwd, (config or {}).get("model", ""), result)
                    elif agent_id == "claude":
                        rows = read_claude_models(process, result)
                    else:
                        rows = read_command_models(agent_id, process)
                    process.check()
                    if agent_id == "pi":
                        process.close()
                        process = None
                        try:
                            process = Process(launch, ["--help"], cwd, cancellation,
                                              max(.01, timeout - (time.monotonic() - started)))
                            process.finish_input()
                            output = []
                            while len(process.eof) < 2 or process.child.poll() is None:
                                record = process.read()
                                if record:
                                    output.append(record[1])
                            line = next((line for line in "".join(output).splitlines() if "--thinking" in line and "off" in line), "")
                            levels = re.findall(r"\b(off|minimal|low|medium|high|xhigh|max)\b", line)
                            result["parameters"] = compact(select("thinking", levels, "CLI 会按模型能力调整思考档位。")) if process.child.returncode == 0 else []
                        except (AgentError, OSError) as exc:
                            if isinstance(exc, AgentError) and exc.kind == "cancelled":
                                raise
                            result["parameters"] = []
                            result["parameterMessage"] = "无法读取此版本 Pi 的思考档位，沿用 CLI 配置。"
                    if agent_id in ("codex", "pi", "opencode"):
                        if process:
                            process.close()
                            process = None
                        try:
                            args = {"codex": ["app-server"], "pi": ["--mode", "rpc", "--no-session", "--no-tools"],
                                    "opencode": ["debug", "config"]}[agent_id]
                            if agent_id == "pi" and config.get("model"):
                                args.extend(["--model", config["model"]])
                            process = Process(launch, args, cwd, cancellation,
                                              max(.01, min(8, timeout - (time.monotonic() - started))),
                                              max_output=8 * 1024 * 1024, max_line=8 * 1024 * 1024)
                            if agent_id == "codex":
                                result["defaults"], standard, result["inheritModelDefaults"] = codex_defaults(process)
                                if standard:
                                    for row in rows:
                                        for field in row.get("parameters", []):
                                            if field["key"] == "serviceTier" and not any(item["value"] == "default" for item in field["options"]):
                                                field["options"].insert(0, {"value": "default", "label": "标准"})
                            elif agent_id == "pi":
                                result["defaults"] = pi_defaults(process)
                            else:
                                result["defaults"] = opencode_defaults(process, config.get("model", ""))
                        except (AgentError, OSError) as exc:
                            if isinstance(exc, AgentError) and exc.kind == "cancelled":
                                raise
                            result["defaults"] = {}
                            result["defaultsMessage"] = "未能读取本机当前值，请明确选择参数或刷新重试。"
                    return {**result, "models": rows, "status": "ready" if rows else "empty",
                            "message": "" if rows else "CLI 未提供可用模型，可手动输入 ID"}
                finally:
                    if process:
                        process.close()
        except (AgentError, OSError) as exc:
            return self._failed(result, exc)
        finally:
            if acquired:
                self.slots.release()

    def close(self):
        deadline = time.monotonic() + 5
        with self.condition:
            while self.flights and time.monotonic() < deadline:
                self.condition.wait(.1)
