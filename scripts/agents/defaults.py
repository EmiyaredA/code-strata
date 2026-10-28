"""Read only applied model settings, never return raw config or send prompts."""
import json
import time

from .runtime import AgentError


def setting(value, source, label=None):
    if not isinstance(value, str) or len(value) > 256 or any(ord(char) < 32 for char in value):
        return None
    return {"value": value, "source": source, **({"label": label} if label else {})}


def keep(values):
    return {key: value for key, value in values.items() if value is not None}


def exchange(process, request, protocol="rpc"):
    process.send(json.dumps(request) + "\n")
    while True:
        record = process.read()
        if record is None:
            if process.child.poll() is not None and "stdout" in process.eof:
                raise AgentError("unsupported", "此版本未提供配置读取接口")
            continue
        if record[0] != "stdout":
            continue
        try:
            message = json.loads(record[1])
        except ValueError as exc:
            raise AgentError("protocol", "配置读取响应格式无效") from exc
        if not isinstance(message, dict):
            raise AgentError("protocol", "配置读取响应格式无效")
        if protocol == "claude":
            if message.get("type") != "control_response":
                continue
            response = message.get("response") or {}
            if response.get("request_id") != request["request_id"]:
                continue
            if response.get("subtype") != "success":
                raise AgentError("unsupported", "此版本未提供已应用配置")
            result = response.get("response")
        elif protocol == "pi":
            if message.get("id") != request["id"]:
                continue
            if message.get("success") is not True:
                raise AgentError("unsupported", "Pi 未提供当前配置")
            result = message.get("data")
        else:
            if message.get("id") != request["id"]:
                continue
            if "error" in message:
                raise AgentError("unsupported", "此版本未提供已应用配置")
            result = message.get("result")
        if not isinstance(result, dict):
            raise AgentError("protocol", "配置读取响应缺少结果")
        return result


def codex_defaults(process):
    exchange(process, {"id": 1, "method": "initialize", "params": {
        "clientInfo": {"name": "code-strata", "version": "1"}, "capabilities": {"experimentalApi": True}}})
    process.send(json.dumps({"method": "initialized"}) + "\n")
    result = exchange(process, {"id": 2, "method": "config/read", "params": {"includeLayers": False}})
    config = result.get("config")
    if not isinstance(config, dict):
        raise AgentError("protocol", "Codex 未返回有效配置")
    tier = config.get("service_tier")
    tier = "priority" if tier == "fast" else tier
    values = keep({"model": setting(config.get("model"), "Codex 配置"),
                   "reasoningEffort": setting(config.get("model_reasoning_effort"), "Codex 配置"),
                   "serviceTier": setting(tier, "Codex 配置", "标准" if tier == "default" else None)})
    inherited = [key for key, raw in (("reasoningEffort", "model_reasoning_effort"), ("serviceTier", "service_tier"))
                 if raw in config and config[raw] is None]
    return values, "service_tier" in config, inherited


def claude_defaults(process, initialized):
    values = {}
    fast = initialized.get("fast_mode_state")
    if fast in ("on", "off"):
        values["fastMode"] = setting("true" if fast == "on" else "false", "Claude 当前会话", "开启" if fast == "on" else "关闭")
    # Older versions can still identify the resolved default model without get_settings.
    default = next((row for row in initialized.get("models", []) if isinstance(row, dict) and row.get("value") == "default"), {})
    if default.get("resolvedModel"):
        values["model"] = setting(default["resolvedModel"], "Claude 模型解析")
    deadline = process.deadline
    try:
        process.deadline = min(deadline, time.monotonic() + 8)
        response = exchange(process, {"type": "control_request", "request_id": "code-strata-settings",
                                     "request": {"subtype": "get_settings"}}, "claude")
        applied = response.get("applied") or {}
        if isinstance(applied, dict):
            values.update(keep({"model": setting(applied.get("model"), "Claude 已应用配置"),
                                "reasoningEffort": setting(applied.get("effort"), "Claude 已应用配置")}))
    except AgentError as exc:
        if exc.kind == "cancelled":
            raise
    finally:
        process.deadline = deadline
    return keep(values)


def acp_defaults(created):
    values = {}
    for item in created.get("configOptions") or []:
        if not isinstance(item, dict):
            continue
        key = "model" if item.get("category") == "model" or item.get("id") == "model" else \
              "reasoningEffort" if item.get("category") == "thought_level" or item.get("id") == "reasoning_effort" else None
        if key:
            value = setting(item.get("currentValue"), "ACP 当前会话")
            if value:
                values[key] = value
    return values


def pi_defaults(process):
    response = exchange(process, {"id": "code-strata-state", "type": "get_state"}, "pi")
    model = response.get("model") or {}
    identifier = None
    if isinstance(model, dict) and all(isinstance(model.get(key), str) and model[key] not in ("", "unknown") for key in ("provider", "id")):
        identifier = model["provider"] + "/" + model["id"]
    return keep({"model": setting(identifier, "Pi 当前会话"),
                 "thinking": setting(response.get("thinkingLevel"), "Pi 当前会话")})


def command_json(process):
    process.finish_input()
    output = []
    while len(process.eof) < 2 or process.child.poll() is None:
        record = process.read()
        if record and record[0] == "stdout":
            output.append(record[1])
    if process.child.returncode:
        raise AgentError("unsupported", "CLI 未提供可读取配置")
    try:
        config = json.loads("".join(output))
    except ValueError as exc:
        raise AgentError("protocol", "配置读取响应格式无效") from exc
    if not isinstance(config, dict):
        raise AgentError("protocol", "配置读取响应格式无效")
    return config


def opencode_defaults(process, model):
    config = command_json(process)
    agent_id = config.get("default_agent")
    agents = config.get("agent") or {}
    agent = agents.get(agent_id, {}) if isinstance(agents, dict) and isinstance(agent_id, str) else {}
    if not isinstance(agent, dict):
        agent = {}
    selected_model = agent.get("model") or config.get("model")
    if isinstance(selected_model, dict):
        provider, model_id = selected_model.get("providerID"), selected_model.get("modelID")
        selected_model = f"{provider}/{model_id}" if isinstance(provider, str) and isinstance(model_id, str) else None
    values = keep({"model": setting(selected_model, "OpenCode 配置")})
    if not agent.get("variant"):
        values["variant"] = setting("", "OpenCode 配置", "未启用变体")
    elif not model or model == selected_model:
        values["variant"] = setting(agent["variant"], "OpenCode Agent 配置")
    return values


def config_signature(agent_id, env):
    """Invalidate cached values when known user settings or selection env change."""
    from pathlib import Path
    home = Path.home()
    xdg = Path(env.get('XDG_CONFIG_HOME') or home / '.config')
    paths = {
        'codex': [Path(env.get('CODEX_HOME') or home / '.codex') / 'config.toml'],
        'claude': [Path(env.get('CLAUDE_CONFIG_DIR') or home / '.claude') / 'settings.json'],
        'pi': [Path(env.get('PI_CODING_AGENT_DIR') or home / '.pi/agent') / 'settings.json'],
        'opencode': [xdg / 'opencode/opencode.json', xdg / 'opencode/opencode.jsonc'],
    }.get(agent_id, [])
    if agent_id == 'opencode' and env.get('OPENCODE_CONFIG'):
        paths.append(Path(env['OPENCODE_CONFIG']))
    stamps = []
    for path in paths:
        try:
            stat = path.stat()
            stamps.append((str(path), stat.st_mtime_ns, stat.st_size))
        except OSError:
            stamps.append((str(path), None, None))
    variables = ('ANTHROPIC_MODEL', 'CLAUDE_CODE_EFFORT_LEVEL', 'CLAUDE_CODE_DISABLE_FAST_MODE') if agent_id == 'claude' else ()
    return tuple(stamps), tuple((key, env.get(key)) for key in variables)
