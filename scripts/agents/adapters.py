"""Declarative CLI definitions and small, explicit result parsers."""
from dataclasses import dataclass
import json
import re

from .runtime import AgentError

PROMPT = "Reply with exactly CODESTRATA_OK. Do not use tools, run commands, or read or write files."
MARKER = "CODESTRATA_OK"


@dataclass(frozen=True)
class Definition:
    id: str
    name: str
    bins: tuple
    args: tuple
    format: str
    model_flag: str = "--model"

    def test_args(self, model, parameters=None):
        args = list(self.args)
        if model and self.id != "dsh":
            args.extend([self.model_flag, model])
        parameters = parameters or {}
        if self.id == "codex":
            for key, config_key in (("reasoningEffort", "model_reasoning_effort"), ("serviceTier", "service_tier")):
                if parameters.get(key):
                    args.extend(["-c", f"{config_key}={json.dumps(parameters[key])}"])
        elif self.id == "opencode" and parameters.get("variant"):
            args.extend(["--variant", parameters["variant"]])
        elif self.id == "claude":
            if parameters.get("reasoningEffort"):
                args.extend(["--effort", parameters["reasoningEffort"]])
            if parameters.get("fastMode"):
                args.extend(["--settings", json.dumps({"fastMode": parameters["fastMode"] == "true"})])
        elif self.id == "pi" and parameters.get("thinking"):
            args.extend(["--thinking", parameters["thinking"]])
        if self.id == "codex":
            args.append("-")
        return args


DEFINITIONS = (
    Definition("codex", "Codex", ("codex",),
               ("exec", "--json", "--skip-git-repo-check", "--sandbox", "read-only", "--ephemeral"), "codex"),
    Definition("opencode", "OpenCode", ("opencode", "opencode-cli"),
               ("run", "--format", "json"), "opencode"),
    Definition("dsh", "DeepSeek Harness", ("dsh",), ("--profile", "acp"), "acp"),
    Definition("claude", "Claude Code", ("claude",),
               ("-p", "--output-format", "json", "--tools", "", "--max-turns", "1"), "claude"),
    Definition("pi", "Pi", ("pi",), ("--print", "--no-session", "--no-tools"), "plain"),
)
BY_ID = {item.id: item for item in DEFINITIONS}


def failure(message, fallback="protocol"):
    if re.search(r"(?i)(unauthenticated|not authenticated|not signed in|not logged in|authentication|unauthorized|invalid.{0,12}(api.key|token)|missing.{0,12}(credential|api.key)|no api.?key|MISSING_CREDENTIAL|DSH_PROVIDER_AUTH_FAILED|\b401\b|请.*登录)", message):
        return AgentError("auth", "CLI 登录或凭据不可用，请在对应 CLI 中完成配置后重试")
    if re.search(r"(?i)(model.{0,60}(not found|invalid|unknown|not available|does not exist)|unknown model|invalid model|模型.*(无效|不存在))", message):
        return AgentError("model", "模型不可用，请检查模型 ID 或从列表中重新选择")
    return AgentError(fallback, "CLI 调用失败，请展开详情检查配置与返回信息")


def parse_result(definition, stdout, stderr, returncode):
    text, completed, errors = "", False, []
    if definition.format == "plain":
        text, completed = stdout.strip(), returncode == 0
    else:
        records = []
        if definition.format == "claude":
            try:
                records = [json.loads(stdout)]
            except ValueError:
                pass
        else:
            for line in stdout.splitlines():
                try:
                    records.append(json.loads(line))
                except ValueError:
                    if line.strip():
                        errors.append("invalid JSON output")
        for event in records:
            if not isinstance(event, dict):
                errors.append("invalid JSON event")
                continue
            kind = event.get("type")
            if definition.format == "codex":
                item = event.get("item") or {}
                if kind == "item.completed" and isinstance(item, dict) and item.get("type") == "agent_message":
                    text = item.get("text", "")
                completed = completed or kind == "turn.completed"
                if kind in ("turn.failed", "error"):
                    errors.append(json.dumps(event, ensure_ascii=False))
            elif definition.format == "opencode":
                part = event.get("part") or {}
                if kind == "text" and isinstance(part, dict):
                    text += part.get("text", "")
                if kind == "step_finish":
                    completed = True
                if kind == "error":
                    errors.append(json.dumps(event, ensure_ascii=False))
            elif definition.format == "claude":
                completed = kind == "result"
                text = event.get("result", "")
                if event.get("is_error") or str(event.get("subtype", "")).startswith("error"):
                    errors.append(json.dumps(event, ensure_ascii=False))
    if returncode or errors:
        raise failure("\n".join(errors) + "\n" + stderr + "\n" + stdout)
    if not completed:
        raise AgentError("protocol", "CLI 没有返回完整的完成事件")
    if not isinstance(text, str) or text.strip() != MARKER:
        raise failure(stderr + "\n" + stdout, "response")
    return text.strip()
