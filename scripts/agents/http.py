"""Agent HTTP domain routing. Authentication stays at the server boundary."""
import re

from .config import validate_settings
from .service import ConflictError

TEST_ROUTE = re.compile(r"/api/agents/tests/([a-f0-9]{32})(/cancel)?")


def handles(path):
    return path in ("/api/settings", "/api/agents", "/api/agents/detect", "/api/agents/tests", "/api/agents/models") or bool(TEST_ROUTE.fullmatch(path))


def dispatch(service, method, path, body=None):
    try:
        if method == "GET":
            if path == "/api/settings":
                return 200, service.store.read()
            if path == "/api/agents":
                return 200, service.agents()
            match = TEST_ROUTE.fullmatch(path)
            if match and not match[2]:
                return 200, service.result(match[1])
        if method == "POST":
            if path == "/api/agents/models":
                return 200, service.model_catalog.get(body)
            if path == "/api/settings":
                return 200, service.store.save(body)
            if path == "/api/agents/detect":
                if set(body) - {"agents"}:
                    raise ValueError("检测参数无效")
                configs = None
                if "agents" in body:
                    configs = validate_settings({"version": 1, "agents": body["agents"]})["agents"]
                return 200, service.agents(force=True, configs=configs)
            if path == "/api/agents/tests":
                return 202, service.start_test(body)
            match = TEST_ROUTE.fullmatch(path)
            if match and match[2]:
                return 200, service.cancel(match[1])
        return 405, {"error": "不支持的请求方式"}
    except ConflictError as exc:
        return 409, {"error": str(exc)}
    except KeyError:
        return 404, {"error": "测试记录不存在或已过期"}
    except ValueError as exc:
        return 422, {"error": str(exc)}
    except OSError:
        return 500, {"error": "无法保存设置，请检查配置目录权限；当前设置未改变"}
