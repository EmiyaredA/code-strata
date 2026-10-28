"""A local fake CLI. Never imports an agent SDK or contacts a provider."""
import json
import os
from pathlib import Path
import sys
import time

args = sys.argv[1:]
mode = os.environ.get("CODE_STRATA_FAKE_MODE", "success")
trace = os.environ.get("CODE_STRATA_FAKE_TRACE")


def record(value):
    if trace:
        with open(trace, "a") as output:
            output.write(json.dumps(value) + "\n")


def emit(value):
    print(json.dumps(value), flush=True)


record({"args": args, "cwd": os.getcwd(), "pid": os.getpid()})
if args == ["--version"]:
    if mode == "version_fail":
        sys.exit(2)
    print("fake-agent 1.2.3", flush=True)
    sys.exit()
if args == ["--help"]:
    if mode == "help_hang":
        time.sleep(30)
    print("--thinking <level> Set thinking level: off, minimal, low, medium, high, xhigh, max")
    sys.exit()
if args == ["app-server"]:
    for line in sys.stdin:
        request = json.loads(line)
        record(request)
        if mode == "defaults_hang":
            continue
        if request.get("method") == "initialize":
            result = {}
        elif request.get("method") == "config/read":
            if mode == "defaults_unsupported":
                emit({"id": request['id'], "error": {"code": -32601}})
                continue
            result = {"config": {"model": "provider/model", "model_reasoning_effort": None if mode == "defaults_model" else "high",
                                 "service_tier": None if mode == "defaults_model" else "default", "apiKey": "never-return-config-secret"}}
        else:
            continue
        emit({"id": request['id'], "result": result})
    sys.exit()
if args[:2] == ["debug", "config"]:
    emit({"model": "provider/model", "default_agent": "build", "agent": {"build": {}}, "apiKey": "never-return-config-secret"})
    sys.exit()
if args[:2] == ["--mode", "rpc"]:
    for line in sys.stdin:
        request = json.loads(line)
        record(request)
        if request.get('type') == 'get_state':
            emit({"id": request['id'], "type": "response", "success": True,
                  "data": {"model": {"provider": "provider", "id": "model", "baseUrl": "never-return-config-secret"}, "thinkingLevel": "medium"}})
    sys.exit()
metadata_command = args[:2] == ["debug", "models"] or args[:1] in (["models"], ["--list-models"])
if metadata_command:
    if mode == "models_hang":
        time.sleep(30)
    if mode == "models_slow":
        time.sleep(.2)
    if mode == "models_unsupported":
        print("unrecognized subcommand models", file=sys.stderr)
        sys.exit(2)
    if mode == "models_malformed":
        print("broken catalog")
        sys.exit()
    if args[0] == "debug":
        models = [{"slug": "provider/model", "display_name": "Readable Model", "base_instructions": "do not expose this"},
                  {"slug": "provider/model", "display_name": "duplicate"},
                  {"slug": "hidden", "visibility": "hidden"}, {"slug": "no-name"}]
        models[0].update(supported_reasoning_levels=[{"effort": "low"}, {"effort": "high"}],
                         service_tiers=[{"id": "priority", "name": "Fast"}], default_reasoning_level="low")
        if mode == "models_empty":
            models = []
        if mode == "models_big":
            models[0]["base_instructions"] = "x" * 600000
        if mode == "models_overflow":
            models[0]["base_instructions"] = "x" * (9 * 1024 * 1024)
        if mode == "models_many":
            models = [{"slug": f"provider/model-{index}", "display_name": f"Model {index}"} for index in range(150)]
        emit({"models": models})
    elif args[0] == "models":
        if mode != "models_empty":
            print('provider/model\n{\n "name": "Readable Model",\n "variants": {"low": {}, "high": {}},\n "limit": {"context": 1000}\n}\nprovider/no-name\nprovider/model')
    else:
        print("provider  model  context  max-out")
        if mode != "models_empty":
            print("\x1b[32mprovider  model\x1b[0m  10000  1000\nprovider  no-name  1000  100\nprovider  model  10000  1000")
    sys.exit()
if "--input-format" in args:
    for line in sys.stdin:
        request = json.loads(line)
        record(request)
        if mode == "models_hang":
            continue
        if mode == "models_slow":
            time.sleep(.2)
        info = {"models": [{"value": "provider/model", "displayName": "Readable Model", "supportsEffort": True,
                            "supportedEffortLevels": ["low", "high"], "supportsFastMode": True}, {"value": "no-name"}]}
        if mode == "models_empty":
            info = {"models": []}
        elif mode == "models_unsupported":
            info = {"commands": []}
        if request.get('request', {}).get('subtype') == 'get_settings':
            if mode == 'defaults_unsupported':
                emit({"type": "control_response", "response": {"subtype": "error", "request_id": request["request_id"], "error": "Unknown request"}})
                continue
            info = {"applied": {"model": "provider/model", "effort": "low"},
                    "effective": {"apiKey": "never-return-config-secret"}}
        else:
            info["fast_mode_state"] = "off"
        emit({"type": "control_response", "response": {"subtype": "success",
             "request_id": request["request_id"], "response": info}})
    sys.exit()
if args[:2] == ["--profile", "acp"]:
    session = "fake-session"
    for line in sys.stdin:
        request = json.loads(line)
        record(request)
        method = request.get("method")
        if mode == "models_hang":
            continue
        if mode == "models_slow":
            time.sleep(.1)
        if method == "initialize":
            result = {"protocolVersion": 1, "agentCapabilities": {}}
        elif method == "session/new":
            if mode == "models_logs":
                print("[llm-deepseek-account] model listing loaded 2 models", flush=True)
            result = {"sessionId": session, "configOptions": [{"id": "model", "category": "model",
                "currentValue": "provider/model", "options": [{"value": "provider/model", "name": "Fake Model"}]}]}
            result["configOptions"].append({"id": "reasoning_effort", "category": "thought_level", "type": "select",
                                            "currentValue": "off", "options": [{"value": "off", "name": "Off"}, {"value": "high", "name": "High"}]})
            if mode == "models_grouped":
                result["configOptions"][0]["options"] = [{"name": "Provider A", "options": [
                    {"value": "opaque:id:1", "name": "Model One"}, {"value": "opaque:id:1"}, {"value": "opaque:id:2"}]}]
            elif mode == "models_empty":
                result["configOptions"][0]["options"] = []
            elif mode == "models_unsupported":
                result["configOptions"] = []
        elif method == "session/set_config_option":
            result = {"configOptions": [{"id": "reasoning_effort", "category": "thought_level", "type": "select",
                       "currentValue": "high", "options": [{"value": "low", "name": "Low"}, {"value": "high", "name": "High"}]}]}
        elif method == "session/prompt":
            if mode == "hang":
                continue
            if mode == "auth":
                emit({"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32000, "message": "MISSING_CREDENTIAL"}})
                continue
            if mode == "permission":
                emit({"jsonrpc": "2.0", "id": "permission-1", "method": "session/request_permission", "params": {"sessionId": session, "options": []}})
            emit({"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": session,
                "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "CODESTRATA_OK"}}}})
            result = {"stopReason": "end_turn"}
        elif method == "session/close":
            emit({"jsonrpc": "2.0", "id": request["id"], "result": {}})
            break
        elif method == "session/cancel":
            continue
        else:
            continue
        emit({"jsonrpc": "2.0", "id": request["id"], "result": result})
    sys.exit()

prompt = sys.stdin.read()
record({"prompt": prompt})
if mode == "hang":
    time.sleep(30)
if mode == "overflow":
    print("x" * 300000)
    sys.exit()
if mode == "empty":
    sys.exit()
if mode == "malformed":
    print("not JSON")
    sys.exit()
if mode == "auth":
    print("authentication required", file=sys.stderr)
    print('authorization=Bearer sensitive-token api_key="sk-secret-test-value"', file=sys.stderr)
text = "CODESTRATA_OK" if mode != "wrong" else "different response"
if args[0] == "exec":
    emit({"type": "item.completed", "item": {"type": "agent_message", "text": text}})
    if mode in ("auth", "protocol_error"):
        emit({"type": "turn.failed", "error": {"message": "authentication required" if mode == "auth" else "provider error"}})
    elif mode != "incomplete":
        emit({"type": "turn.completed", "usage": {}})
elif args[0] == "run":
    emit({"type": "text", "part": {"text": text}})
    emit({"type": "step_finish", "part": {"reason": "stop"}})
    if mode in ("auth", "protocol_error"):
        emit({"type": "error", "error": {"message": "authentication required" if mode == "auth" else "provider error"}})
elif args[0] == "-p":
    emit({"type": "result", "subtype": "success", "result": text, "is_error": mode in ("auth", "protocol_error")})
elif args[0] == "--print":
    print(text)
    if mode in ("auth", "protocol_error"):
        sys.exit(1)
