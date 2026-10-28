"""Versioned, user-owned agent preferences. No credentials or probe output."""
import json
import os
from pathlib import Path
import tempfile
from threading import Lock

AGENT_IDS = ("codex", "opencode", "dsh", "claude", "pi")


def defaults():
    return {"version": 1, "defaultAgentId": None,
            "agents": {key: {"executablePath": "", "model": ""} for key in AGENT_IDS}}


PARAMETER_KEYS = {"codex": {"reasoningEffort", "serviceTier"}, "opencode": {"variant"},
                  "dsh": {"reasoningEffort"}, "claude": {"reasoningEffort", "fastMode"},
                  "pi": {"thinking"}}


def validate_agent(value, agent_id=None):
    if not isinstance(value, dict) or set(value) - {"executablePath", "model", "parameters"}:
        raise ValueError("Agent 配置字段无效")
    result = {}
    for key, limit in (("executablePath", 4096), ("model", 256)):
        text = value.get(key, "")
        if not isinstance(text, str) or len(text) > limit or any(ord(c) < 32 for c in text):
            raise ValueError("可执行路径或模型 ID 无效")
        result[key] = text.strip()
    if result["executablePath"]:
        path = Path(result["executablePath"]).expanduser()
        if not path.is_absolute():
            raise ValueError("可执行文件请填写绝对路径")
        result["executablePath"] = str(path)
    parameters = value.get("parameters", {})
    allowed = PARAMETER_KEYS[agent_id] if agent_id else set().union(*PARAMETER_KEYS.values())
    if not isinstance(parameters, dict) or set(parameters) - allowed:
        raise ValueError("此 Agent 不支持该参数配置")
    clean = {}
    for key, item in parameters.items():
        if not isinstance(item, str) or len(item) > 128 or any(ord(c) < 32 for c in item):
            raise ValueError("Agent 参数值无效")
        if key == "fastMode" and item not in ("", "true", "false"):
            raise ValueError("快速模式配置无效")
        if item.strip():
            clean[key] = item.strip()
    if clean:
        result["parameters"] = clean
    return result


def validate_settings(value):
    if not isinstance(value, dict) or set(value) - {"version", "defaultAgentId", "agents"}:
        raise ValueError("设置格式无效")
    if type(value.get("version")) is not int or value["version"] != 1:
        raise ValueError("不支持的设置版本")
    selected = value.get("defaultAgentId")
    if selected is not None and selected not in AGENT_IDS:
        raise ValueError("未知的默认 Agent")
    agents = value.get("agents")
    if not isinstance(agents, dict) or set(agents) - set(AGENT_IDS):
        raise ValueError("未知的 Agent 配置")
    result = defaults()
    result["defaultAgentId"] = selected
    for key, item in agents.items():
        result["agents"][key] = validate_agent(item, key)
    return result


class SettingsStore:
    def __init__(self, path=None):
        root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config").expanduser()
        if not root.is_absolute():
            root = Path.home() / ".config"
        self.path = Path(path) if path is not None else root / "code-strata" / "settings.json"
        self.lock = Lock()

    def read(self):
        with self.lock:
            try:
                if not self.path.exists():
                    return {"settings": defaults(), "error": None}
                if self.path.stat().st_size > 16384:
                    raise ValueError("设置文件过大")
                value = validate_settings(json.loads(self.path.read_text(encoding="utf-8")))
                return {"settings": value, "error": None}
            except (OSError, ValueError) as exc:
                return {"settings": defaults(), "error": f"无法读取设置，请检查或重新保存：{exc}"}

    def save(self, value):
        value = validate_settings(value)
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                                 prefix=".settings-", delete=False) as output:
                    temporary = output.name
                    json.dump(value, output, ensure_ascii=False, indent=2)
                    output.write("\n")
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, self.path)
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)
        return {"settings": value, "error": None}
