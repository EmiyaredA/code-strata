"""Minimal ACP v1 client for one DSH smoke test, with no OD profile dependency."""
import json
import re
import time

from .adapters import PROMPT, MARKER, failure
from .runtime import AgentError


class AcpTest:
    def __init__(self, process, cwd):
        self.process, self.cwd = process, str(cwd)
        self.serial, self.session, self.text = 0, None, ""

    def send(self, method, params, notification=False):
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            self.serial += 1
            message["id"] = self.serial
        self.process.send(json.dumps(message) + "\n")
        return message.get("id")

    def call(self, method, params):
        expected = self.send(method, params)
        while True:
            record = self.process.read()
            if record is None:
                if self.process.child.poll() is not None and "stdout" in self.process.eof:
                    raise failure(self.process.diagnostics()["stderr"] + " ACP process exited")
                continue
            source, line = record
            if source != "stdout":
                continue
            # Native DSH provider discovery can emit tagged diagnostics on stdout.
            # Ignore only that log framing; malformed protocol frames still fail.
            clean = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", line).strip()
            if not clean or re.match(r"^\[[A-Za-z0-9_.:-]+\]\s", clean):
                continue
            try:
                message = json.loads(clean)
            except ValueError as exc:
                raise AgentError("protocol", "ACP 返回了无效的 JSON") from exc
            if not isinstance(message, dict):
                raise AgentError("protocol", "ACP 返回格式无效")
            if message.get("method") == "session/update":
                params = message.get("params") or {}
                if not isinstance(params, dict):
                    raise AgentError("protocol", "ACP 更新格式无效")
                if params.get("sessionId") != self.session:
                    continue
                update = params.get("update") or {}
                if not isinstance(update, dict):
                    raise AgentError("protocol", "ACP 更新格式无效")
                if update.get("sessionUpdate") == "agent_message_chunk":
                    content = update.get("content") or {}
                    if isinstance(content, dict) and content.get("type") == "text":
                        text = content.get("text", "")
                        if not isinstance(text, str):
                            raise AgentError("protocol", "ACP 文本格式无效")
                        self.text += text
            elif "method" in message and "id" in message:
                response = {"jsonrpc": "2.0", "id": message["id"]}
                if message["method"] == "session/request_permission":
                    response["result"] = {"outcome": {"outcome": "cancelled"}}
                else:
                    response["error"] = {"code": -32601, "message": "Client tool operations are unavailable during a connection test"}
                self.process.send(json.dumps(response) + "\n")
            elif message.get("id") == expected:
                if "error" in message:
                    raise failure(json.dumps(message["error"], ensure_ascii=False))
                result = message.get("result")
                if not isinstance(result, dict):
                    raise AgentError("protocol", "ACP 响应缺少结果")
                return result

    def set_model(self, created, model):
        options = created.get("configOptions") or []
        if not isinstance(options, list):
            raise AgentError("protocol", "ACP 模型配置格式无效")
        selector = next((item for item in options if isinstance(item, dict) and
                         (item.get("category") == "model" or item.get("id") == "model")), None)
        def values(items):
            result = []
            for item in items:
                if isinstance(item, dict):
                    if "value" in item:
                        result.append(item["value"])
                    result.extend(values(item.get("options") or []))
            return result
        if not selector or model not in values(selector.get("options") or []):
            raise AgentError("model", "DeepSeek Harness 未提供该模型 ID；请清空模型覆盖或使用 CLI 中配置的模型 ID")
        return self.call("session/set_config_option", {"sessionId": self.session,
                  "configId": selector["id"], "value": model})

    def run(self, model, parameters=None):
        self.call("initialize", {"protocolVersion": 1, "clientCapabilities": {},
                                "clientInfo": {"name": "code-strata", "version": "1"}})
        created = self.call("session/new", {"cwd": self.cwd, "mcpServers": []})
        self.session = created.get("sessionId")
        if not isinstance(self.session, str) or not self.session:
            raise AgentError("protocol", "ACP 未返回会话 ID")
        if model:
            created = self.set_model(created, model)
        if parameters and parameters.get("reasoningEffort"):
            from .parameters import acp_parameters
            descriptor = next(iter(acp_parameters(created)), None)
            value = parameters["reasoningEffort"]
            if not descriptor or value not in {item["value"] for item in descriptor["options"]}:
                raise AgentError("parameters", "此 DeepSeek Harness 模型不支持所选推理强度，请刷新或重新选择")
            selector = next(item for item in created["configOptions"] if
                            item.get("category") == "thought_level" or item.get("id") == "reasoning_effort")
            self.call("session/set_config_option", {"sessionId": self.session,
                      "configId": selector["id"], "value": value})
        result = self.call("session/prompt", {"sessionId": self.session,
                           "prompt": [{"type": "text", "text": PROMPT}]})
        if result.get("stopReason") != "end_turn" or self.text.strip() != MARKER:
            raise AgentError("response", "DeepSeek Harness 未返回预期测试响应或未正常结束")
        self.call("session/close", {"sessionId": self.session})
        self.session = None
        return self.text.strip()

    def cleanup(self):
        if not self.session:
            return
        try:
            self.send("session/cancel", {"sessionId": self.session}, notification=True)
            self.send("session/close", {"sessionId": self.session})
            # Give the CLI a short opportunity to flush before terminating the group.
            time.sleep(.1)
        except AgentError:
            pass
