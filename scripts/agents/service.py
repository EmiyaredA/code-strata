"""Process-local detection cache and single-flight connection tests."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import tempfile
import threading
import time
import uuid

from .acp import AcpTest
from .adapters import DEFINITIONS, BY_ID, PROMPT, parse_result, failure
from .config import SettingsStore, validate_agent
from .parameters import check_parameters
from .runtime import AgentError, Process, resolve_launch, redact
from .model_catalog import ModelCatalog


class ConflictError(ValueError):
    pass


class AgentService:
    def __init__(self, settings_path=None, node=None, test_timeout=90):
        self.store, self.node = SettingsStore(settings_path), node
        self.test_timeout = test_timeout
        self.lock, self.detect_lock = threading.Lock(), threading.Lock()
        self.cache, self.cache_key, self.cache_at = [], None, 0
        self.tests, self.closed = {}, False
        self.stop = threading.Event()
        self.model_catalog = ModelCatalog(node, self.stop)

    def _probe(self, definition, config):
        result = {"id": definition.id, "name": definition.name, "status": "not_found",
                  "executablePath": None, "version": None, "message": ""}
        process = None
        try:
            launch = resolve_launch(definition, config, self.node)
            result["executablePath"] = launch["path"]
            with tempfile.TemporaryDirectory(prefix="code-strata-probe-") as cwd:
                process = Process(launch, ["--version"], cwd, self.stop, 15)
                output = []
                while len(process.eof) < 2 or process.child.poll() is None:
                    record = process.read()
                    if record:
                        output.append(record[1])
                if process.child.returncode:
                    raise AgentError("launch", "CLI 已找到，但版本查询失败；请检查路径与运行环境")
                result.update(status="detected", version=redact(" ".join("".join(output).split()))[:180] or None,
                              message="已检测到；模型连接尚未验证")
        except AgentError as exc:
            result.update(status="not_found" if exc.kind == "not_found" else "unavailable", message=str(exc))
        except (OSError, ValueError) as exc:
            result.update(status="unavailable", message=redact(str(exc)))
        finally:
            if process:
                process.close()
        return result

    def agents(self, force=False, configs=None):
        configs = configs if configs is not None else self.store.read()["settings"]["agents"]
        key = json.dumps(configs, sort_keys=True)
        with self.detect_lock:
            if not force and key == self.cache_key and time.monotonic() - self.cache_at < 60:
                return {"agents": copy.deepcopy(self.cache)}
            with ThreadPoolExecutor(max_workers=3) as pool:
                self.cache = list(pool.map(lambda definition: self._probe(definition, configs[definition.id]), DEFINITIONS))
            self.cache_key, self.cache_at = key, time.monotonic()
            return {"agents": copy.deepcopy(self.cache)}

    def start_test(self, body):
        if not isinstance(body, dict) or set(body) - {"agentId", "config"}:
            raise ValueError("连接测试参数无效")
        agent_id = body.get("agentId")
        if not isinstance(agent_id, str) or agent_id not in BY_ID:
            raise ValueError("未知的 Agent")
        config = validate_agent(body.get("config", {}), agent_id)
        with self.lock:
            if self.closed:
                raise ConflictError("服务正在关闭")
            if any(item["result"]["status"] == "running" for item in self.tests.values()):
                raise ConflictError("已有连接测试正在运行，请先取消或等待完成")
            # Only bounded, session-local history; never persist test responses or logs.
            self.tests = dict(list(self.tests.items())[-19:])
            test_id = uuid.uuid4().hex
            job = {"cancel": threading.Event(), "result": {"id": test_id, "agentId": agent_id,
                   "status": "running", "kind": None, "message": "正在连接 CLI…", "response": "",
                   "durationMs": 0, "executablePath": None, "details": {}}}
            self.tests[test_id] = job
            job["thread"] = threading.Thread(target=self._run, args=(job, config), daemon=True)
            job["thread"].start()
            return copy.deepcopy(job["result"])

    def result(self, test_id):
        with self.lock:
            if test_id not in self.tests:
                raise KeyError(test_id)
            return copy.deepcopy(self.tests[test_id]["result"])

    def cancel(self, test_id):
        with self.lock:
            if test_id not in self.tests:
                raise KeyError(test_id)
            self.tests[test_id]["cancel"].set()
            return copy.deepcopy(self.tests[test_id]["result"])

    def _run(self, job, config):
        started, process, acp = time.monotonic(), None, None
        result = copy.deepcopy(job["result"])
        definition = BY_ID[result["agentId"]]
        try:
            launch = resolve_launch(definition, config, self.node)
            result["executablePath"] = launch["path"]
            if job["cancel"].is_set():
                raise AgentError("cancelled", "测试已取消")
            if config.get("parameters") and definition.id != "dsh":
                catalog = self.model_catalog.get({"agentId": definition.id, "config": config}, cancel=job["cancel"],
                                                 timeout=self.test_timeout)
                check_parameters(catalog, config)
            if job["cancel"].is_set():
                raise AgentError("cancelled", "测试已取消")
            if time.monotonic() - started >= self.test_timeout:
                raise AgentError("timeout", "连接测试超时")
            with tempfile.TemporaryDirectory(prefix="code-strata-test-") as cwd:
                try:
                    process = Process(launch, definition.test_args(config["model"], config.get("parameters")), cwd,
                                      job["cancel"], max(.01, self.test_timeout - (time.monotonic() - started)))
                    if definition.format == "acp":
                        acp = AcpTest(process, cwd)
                        text = acp.run(config["model"], config.get("parameters"))
                    else:
                        process.send(PROMPT + "\n")
                        process.finish_input()
                        output = {"stdout": [], "stderr": []}
                        while len(process.eof) < 2 or process.child.poll() is None:
                            record = process.read()
                            if record:
                                output[record[0]].append(record[1])
                        text = parse_result(definition, "".join(output["stdout"]),
                                            "".join(output["stderr"]), process.child.returncode)
                    process.check()
                    result.update(status="success", message="连接成功", response=text)
                finally:
                    if acp:
                        acp.cleanup()
                    if process:
                        result["details"] = process.diagnostics()
                        process.close()
        except AgentError as exc:
            result.update(status="cancelled" if exc.kind == "cancelled" else "failed",
                          kind=exc.kind, message=redact(str(exc)))
        except Exception as exc:
            result.update(status="failed", kind="launch", message="连接测试失败，请检查 CLI 配置",
                          details={"stderr": redact(str(exc))[-8192:]})
        finally:
            result["durationMs"] = round((time.monotonic() - started) * 1000)
            with self.lock:
                if job["cancel"].is_set():
                    result.update(status="cancelled", kind="cancelled", message="测试已取消", response="")
                job["result"] = result

    def close(self):
        with self.lock:
            self.closed = True
            self.stop.set()
            jobs = list(self.tests.values())
            for job in jobs:
                job["cancel"].set()
        for job in jobs:
            job["thread"].join(timeout=5)
        self.model_catalog.close()
