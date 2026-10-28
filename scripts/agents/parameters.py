"""Explicit, bounded option descriptors from native CLI/model capabilities."""
from .runtime import AgentError

LABELS = {"reasoningEffort": "推理强度", "serviceTier": "速度档位", "variant": "模型变体",
          "thinking": "思考强度", "fastMode": "快速模式"}


def select(key, choices, hint=None):
    options, seen = [], set()
    for choice in choices if isinstance(choices, (list, tuple)) else []:
        value = choice.get("value") if isinstance(choice, dict) else choice
        if not isinstance(value, str) or not value.strip() or len(value) > 128 or any(ord(c) < 32 for c in value):
            continue
        value = value.strip()
        if value in seen:
            continue
        seen.add(value)
        label = choice.get("label") if isinstance(choice, dict) else value
        options.append({"value": value, "label": label[:128] if isinstance(label, str) and label else value})
        if len(options) == 64:
            break
    if not options:
        return None
    return {"key": key, "label": LABELS[key], "options": options, **({"hint": hint} if hint else {})}


def compact(*descriptors):
    return [item for item in descriptors if item]


def codex_parameters(row):
    levels = row.get("supported_reasoning_levels")
    reasoning = [{"value": item.get("effort")} for item in levels if isinstance(item, dict)] if isinstance(levels, list) else []
    raw_tiers = row.get("service_tiers")
    tiers = [{"value": item.get("id"), "label": item.get("name") or item.get("label") or item.get("id")}
             for item in raw_tiers if isinstance(item, dict)] if isinstance(raw_tiers, list) else []
    if not tiers and "fast" in (row.get("additional_speed_tiers") or []):
        tiers = [{"value": "priority", "label": "Fast"}]
    return compact(select("reasoningEffort", reasoning), select("serviceTier", tiers, "Fast 档位可能增加用量，具体以 CLI 和账户规则为准。"))


def claude_parameters(row):
    return compact(select("reasoningEffort", row.get("supportedEffortLevels", [])) if row.get("supportsEffort") else None,
                   select("fastMode", [{"value": "true", "label": "开启"}, {"value": "false", "label": "关闭"}],
                          "快速模式可能增加费用，并受账户权限限制。") if row.get("supportsFastMode") else None)


def acp_parameters(created):
    options = created.get("configOptions") or []
    if not isinstance(options, list):
        return []
    selector = next((item for item in options if isinstance(item, dict) and
                     (item.get("category") == "thought_level" or item.get("id") == "reasoning_effort") and
                     item.get("type", "select") == "select"), None)
    if not selector:
        return []
    def flatten(items):
        result = []
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict):
                if "value" in item:
                    result.append({"value": item["value"], "label": item.get("name") or item["value"]})
                else:
                    result.extend(flatten(item.get("options")))
        return result
    return compact(select("reasoningEffort", flatten(selector.get("options"))))


def available_parameters(catalog, model):
    resolved = model or catalog.get("defaults", {}).get("model", {}).get("value")
    row = next((item for item in catalog.get("models", []) if resolved and
                (item["id"] == resolved or item.get("resolvedId") == resolved)), None)
    # ACP options already reflect the selected model; Pi's --thinking is CLI-wide
    # and the CLI itself clamps the requested level to the model's capabilities.
    if catalog.get("agentId") in ("dsh", "pi") or (not model and catalog.get("agentId") == "claude"):
        return catalog.get("parameters", [])
    return row.get("parameters", []) if row else []


def check_parameters(catalog, config):
    if catalog.get("status") not in ("ready", "empty"):
        raise AgentError(catalog.get("kind") or "parameters", catalog.get("message") or "无法确认 CLI 参数支持情况，请刷新后重试")
    descriptors = {item["key"]: item for item in available_parameters(catalog, config["model"])}
    for key, value in config.get("parameters", {}).items():
        descriptor = descriptors.get(key)
        if not descriptor or value not in {item["value"] for item in descriptor["options"]}:
            raise AgentError("parameters", f"当前 CLI 或模型未确认支持该参数：{LABELS[key]}={value}；请刷新配置或重新选择参数")
