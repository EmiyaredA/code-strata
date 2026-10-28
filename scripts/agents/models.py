"""Model catalogs from native CLI metadata. Never sends a generation prompt."""
from bisect import bisect_right
import json
import re

from .acp import AcpTest
from .adapters import failure
from .runtime import AgentError
from .parameters import codex_parameters, claude_parameters, acp_parameters, compact, select
from .defaults import setting, keep, acp_defaults, claude_defaults

ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
SOURCES = {"codex": "codex debug models", "opencode": "opencode models --verbose",
           "pi": "pi --list-models", "claude": "Claude Code initialize", "dsh": "DeepSeek Harness ACP"}
COMMANDS = {"codex": ["debug", "models"], "opencode": ["models", "--verbose"],
            "pi": ["--list-models"], "dsh": ["--profile", "acp"],
            "claude": ["-p", "--input-format", "stream-json", "--output-format", "stream-json",
                       "--verbose", "--tools", "", "--no-session-persistence"]}


def normalize(rows):
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        identifier = row.get("id")
        if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 256:
            continue
        identifier = identifier.strip()
        if identifier in seen or any(ord(c) < 32 for c in identifier):
            continue
        seen.add(identifier)
        label = row.get("label")
        item = {"id": identifier, "label": label.strip()[:256] if isinstance(label, str) and label.strip() else identifier}
        provider = row.get("provider")
        if isinstance(provider, str) and provider.strip():
            item["provider"] = provider.strip()[:128]
        if row.get("parameters"):
            item["parameters"] = row["parameters"]
        if row.get("defaults"):
            item["defaults"] = row["defaults"]
        resolved = row.get("resolvedId")
        if isinstance(resolved, str) and resolved and len(resolved) <= 256 and not any(ord(c) < 32 for c in resolved):
            item["resolvedId"] = resolved
        result.append(item)
    return result


def codex_models(stdout):
    try:
        value = json.loads(stdout)
    except ValueError as exc:
        raise AgentError("protocol", "Codex 模型目录不是有效 JSON") from exc
    models = value.get("models") if isinstance(value, dict) else value
    if not isinstance(models, list):
        raise AgentError("protocol", "Codex 未返回模型列表")
    return normalize({"id": row.get("slug") or row.get("id"),
                      "label": row.get("display_name") or row.get("name"), "parameters": codex_parameters(row),
                      "defaults": keep({"reasoningEffort": setting(row.get("default_reasoning_level"), "模型默认"),
                                        "serviceTier": setting(row.get("default_service_tier") or "default", "模型默认",
                                                               "标准" if not row.get("default_service_tier") or row["default_service_tier"] == "default" else None)
                                        if isinstance(row.get("service_tiers"), list) else None})}
                     for row in models if isinstance(row, dict) and row.get("visibility") != "hidden")


def opencode_models(stdout):
    text = ANSI.sub("", stdout)
    lines, rows, index = text.splitlines(keepends=True), [], 0
    offsets, total = [], 0
    for line in lines:
        offsets.append(total)
        total += len(line)
    while index < len(lines):
        identifier = lines[index].strip()
        index += 1
        if not re.fullmatch(r"[^\s/]+/[^\s]+", identifier):
            continue
        metadata = {}
        if index < len(lines) and lines[index].lstrip().startswith("{"):
            # Verbose output is one provider/model id followed by a JSON object.
            start = offsets[index]
            while start < len(text) and text[start].isspace():
                start += 1
            try:
                metadata, end = json.JSONDecoder().raw_decode(text, start)
            except ValueError as exc:
                raise AgentError("protocol", "OpenCode 模型元数据格式无效") from exc
            index = bisect_right(offsets, max(start, end - 1))
            if not isinstance(metadata, dict):
                raise AgentError("protocol", "OpenCode 模型元数据格式无效")
        rows.append({"id": identifier, "label": metadata.get("name") or metadata.get("displayName"),
                     "provider": identifier.split("/", 1)[0],
                     "parameters": compact(select("variant", list(metadata["variants"]))
                                           if isinstance(metadata.get("variants"), dict) else None)})
    if stdout.strip() and not rows:
        raise AgentError("protocol", "OpenCode 输出中没有可识别的模型 ID")
    return normalize(rows)


def pi_models(stdout):
    lines = [line.strip() for line in ANSI.sub("", stdout).splitlines() if line.strip()]
    header = next((index for index, line in enumerate(lines)
                   if re.match(r"(?i)^provider\s+model(?:\s|$)", line)), None)
    if header is None:
        if not lines or any(re.search(r"(?i)no (available )?models", line) for line in lines):
            return []
        raise AgentError("protocol", "Pi 未返回可识别的模型表格")
    rows = []
    for line in lines[header + 1:]:
        columns = line.split()
        if len(columns) < 2 or re.fullmatch(r"[-─=\s]+", line):
            continue
        provider, model = columns[:2]
        rows.append({"id": f"{provider}/{model}", "provider": provider})
    return normalize(rows)


def acp_models(created):
    options = created.get("configOptions") or []
    if not isinstance(options, list):
        raise AgentError("protocol", "ACP 模型配置格式无效")
    selector = next((item for item in options if isinstance(item, dict) and
                     (item.get("category") == "model" or item.get("id") == "model")), None)
    if selector is None:
        # Legacy ACP versions may expose the older models field instead.
        old = created.get("models") or {}
        if isinstance(old, dict) and isinstance(old.get("availableModels"), list):
            return normalize({"id": row.get("modelId"), "label": row.get("name")}
                             for row in old["availableModels"] if isinstance(row, dict))
        raise AgentError("unsupported", "此版本的 DeepSeek Harness 没有提供模型目录，可手动输入 ID")
    def flatten(items, group=None, depth=0):
        if not isinstance(items, list) or depth > 8:
            raise AgentError("protocol", "ACP 模型选项格式无效")
        rows = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if "value" in item:
                rows.append({"id": item["value"], "label": item.get("name"), "provider": group})
            elif "options" in item:
                rows.extend(flatten(item["options"], item.get("name") or item.get("group"), depth + 1))
        return rows
    return normalize(flatten(selector.get("options") or []))


def read_acp_models(process, cwd, model="", metadata=None):
    client = AcpTest(process, cwd)
    try:
        client.call("initialize", {"protocolVersion": 1, "clientCapabilities": {},
                                  "clientInfo": {"name": "code-strata", "version": "1"}})
        created = client.call("session/new", {"cwd": str(cwd), "mcpServers": []})
        client.session = created.get("sessionId")
        if not isinstance(client.session, str) or not client.session:
            raise AgentError("protocol", "ACP 未返回查询会话 ID")
        rows = acp_models(created)
        initial_defaults = acp_defaults(created)
        if model:
            try:
                created = client.set_model(created, model)
            except AgentError as exc:
                if exc.kind != "model":
                    raise
                # Keep the catalog selectable when an old/manual ID no longer exists.
                created = {}
                if metadata is not None:
                    metadata["parameterMessage"] = "当前模型 ID 不在 CLI 目录中，无法获取其额外参数；可重新选择模型。"
        if metadata is not None:
            metadata["parameters"] = acp_parameters(created)
            metadata["defaults"] = {**initial_defaults, **acp_defaults(created)}
        client.call("session/close", {"sessionId": client.session})
        client.session = None
        return rows
    finally:
        client.cleanup()


def read_claude_models(process, metadata=None):
    request_id = "code-strata-models"
    process.send(json.dumps({"type": "control_request", "request_id": request_id,
                            "request": {"subtype": "initialize", "hooks": None}}) + "\n")
    while True:
        record = process.read()
        if record is None:
            if process.child.poll() is not None and "stdout" in process.eof:
                raise AgentError("unsupported", "Claude Code 未提供初始化模型信息，可手动输入 ID")
            continue
        source, line = record
        if source != "stdout":
            continue
        try:
            event = json.loads(line)
        except ValueError as exc:
            raise AgentError("protocol", "Claude Code 控制响应格式无效") from exc
        if not isinstance(event, dict):
            raise AgentError("protocol", "Claude Code 控制响应格式无效")
        if event.get("type") == "result" and event.get("is_error"):
            raise failure(json.dumps(event))
        if event.get("type") == "control_request":
            process.send(json.dumps({"type": "control_response", "response": {"subtype": "error",
                "request_id": event.get("request_id"), "error": "Unavailable during model discovery"}}) + "\n")
        if event.get("type") != "control_response":
            continue
        response = event.get("response") or {}
        if not isinstance(response, dict) or response.get("request_id") != request_id:
            continue
        if response.get("subtype") == "error":
            raise failure(str(response.get("error", "")))
        info = response.get("response") or {}
        models = info.get("models") if isinstance(info, dict) else None
        if not isinstance(models, list):
            raise AgentError("unsupported", "此版本的 Claude Code 没有提供模型列表，可手动输入 ID")
        default = next((row for row in models if isinstance(row, dict) and row.get("value") == "default"), {})
        if metadata is not None:
            metadata["parameters"] = claude_parameters(default)
            metadata["defaults"] = claude_defaults(process, info)
        return normalize({"id": row.get("value") or row.get("id"),
                          "label": row.get("displayName") or row.get("display_name") or row.get("name"),
                          "resolvedId": row.get("resolvedModel"),
                          "parameters": claude_parameters(row)}
                         for row in models if isinstance(row, dict) and row.get("value") != "default")


def read_command_models(agent_id, process):
    process.finish_input()
    stdout, stderr = [], []
    while len(process.eof) < 2 or process.child.poll() is None:
        record = process.read()
        if record:
            (stdout if record[0] == "stdout" else stderr).append(record[1])
    output, error = "".join(stdout), "".join(stderr)
    if process.child.returncode:
        if re.search(r"(?i)(unrecognized subcommand|unknown (command|option)|unexpected argument|invalid option)", output + error):
            raise AgentError("unsupported", "此 CLI 版本不支持模型目录查询，可手动输入 ID")
        raise failure(output + "\n" + error)
    return {"codex": codex_models, "opencode": opencode_models, "pi": pi_models}[agent_id](output)
