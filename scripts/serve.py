"""Serve the local, read-only architecture board. Requires Python 3.10+."""

import argparse
import errno
import json
import mimetypes
import os
import secrets
import signal
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.client import HTTPConnection
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

from scan import scan_project
from code_analysis.service import CodeSession
from directory_picker import choose_directory, DirectoryPickerUnavailable
from agents.service import AgentService
from agents.http import handles as agent_route, dispatch as agent_dispatch
from exploration.service import ExplorationService
from exploration.http import handles as exploration_route, dispatch as exploration_dispatch

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "board"
DEFAULT_PORT = 8765


def make_server(project=None, mapping=None, node=None, port=0, scc=None, work_dir=None,
                settings_path=None, agent_test_timeout=90, history_path=None, exploration_runner=None,
                exploration_timeout=900, dev=None):
    token = dev['token'] if dev else secrets.token_urlsafe(32)
    state = dict(project=None, mapping=None, data=None, code=None)
    lock = Lock()
    picker_lock = Lock()
    agents = AgentService(settings_path, node, agent_test_timeout)
    exploration_lock = Lock()
    def exploration():
        # Do not create a database until the workspace is used. Tests with an
        # isolated settings file also get an isolated history store by default.
        with exploration_lock:
            if server.exploration is None:
                database = history_path or (Path(settings_path).parent / 'exploration.sqlite3' if settings_path else None)
                service = ExplorationService(agents.store, database, node, scc, work_dir,
                                             runner=exploration_runner, timeout=exploration_timeout)
                service.url = f'http://127.0.0.1:{server.server_port}'
                server.exploration = service
            return server.exploration
    def scan_inputs(project, mapping):
        context = {}
        data = scan_project(project, mapping, node, scc, work_dir, snapshot_context=context)
        return data, CodeSession(data, context)

    if project:
        data, code = scan_inputs(project, mapping)
        state.update(project=str(Path(project).expanduser().resolve()), mapping=mapping,
                     data=data, code=code)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, status, body, content_type="application/json; charset=utf-8"):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode()
            elif isinstance(body, str):
                body = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def allowed_host(self):
            return self.headers.get("Host") in (
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            )

        def api_allowed(self):
            origin = self.headers.get("Origin")
            return (
                self.allowed_host()
                and (
                    origin is None
                    or origin
                    in (
                        f"http://127.0.0.1:{self.server.server_port}",
                        f"http://localhost:{self.server.server_port}",
                    )
                )
                and secrets.compare_digest(self.headers.get("X-Architecture-Token", ""), token)
            )

        def dispatch_request(self, handler, mutation=False):
            if not dev:
                return handler()
            route = urlparse(self.path).path
            with server.reload_lock:
                rejected = server.draining and mutation and route != '/api/explore/tools' and not route.endswith('/cancel')
                if not rejected:
                    server.active_requests += 1
            if rejected:
                return self.send(503, dict(error='开发服务正在自动重载，请稍后重试', retryable=True))
            try:
                return handler()
            finally:
                with server.reload_lock:
                    server.active_requests -= 1

        def do_GET(self):
            return self.dispatch_request(self.get)

        def get(self):
            if not self.allowed_host():
                return self.send(403, {"error": "不允许的来源"})
            path = urlparse(self.path).path
            if exploration_route(path):
                if not self.api_allowed():
                    return self.send(403, {"error": "看板会话无效，请刷新页面"})
                with lock:
                    current = state['data']
                try:
                    status, result = exploration_dispatch(exploration(), 'GET', path, current, query=urlparse(self.path).query)
                except (OSError, ValueError) as exc:
                    return self.send(503, dict(error=str(exc)))
                return self.send(status, result)
            if agent_route(path):
                if not self.api_allowed():
                    return self.send(403, {"error": "看板会话无效，请刷新页面"})
                status, result = agent_dispatch(agents, "GET", path)
                return self.send(status, result)
            if path == "/api/project":
                if not self.api_allowed():
                    return self.send(403, {"error": "看板会话无效，请刷新页面"})
                with lock:
                    return self.send(200, state["data"] or {"demo": True})
            if path.startswith("/api/"):
                return self.send(404, {"error": "接口不存在"})
            if dev:
                return self.frontend()
            rel = path.lstrip("/") or "index.html"
            target = (ASSETS / rel).resolve()
            if not target.is_relative_to(ASSETS) or not target.is_file():
                return self.send(404, "文件不存在", "text/plain; charset=utf-8")
            body = target.read_bytes()
            if target.name == "index.html":
                body = body.replace(
                    b"</head>",
                    f'<meta name="architecture-token" content="{token}"></head>'.encode(),
                )
            return self.send(
                200, body, mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            )

        def frontend(self):
            # Keep API authentication and the page on the same loopback origin;
            # Vite only serves frontend modules, not application API requests.
            frontend = urlparse(dev['frontend'])
            connection = HTTPConnection(frontend.hostname, frontend.port, timeout=15)
            try:
                connection.request('GET', self.path if self.path.startswith('/') else '/',
                                   headers={'Host': frontend.netloc})
                response = connection.getresponse()
                content_type = response.getheader('Content-Type', 'application/octet-stream')
                body = response.read()
                if 'text/html' in content_type:
                    body = body.replace(b'</head>',
                        f'<meta name="architecture-token" content="{token}"><meta name="code-strata-dev" content="1"></head>'.encode())
                return self.send(response.status, body, content_type)
            except OSError:
                return self.send(503, '前端开发服务暂不可用，请查看终端日志', 'text/plain; charset=utf-8')
            finally:
                connection.close()

        def do_POST(self):
            return self.dispatch_request(self.post, mutation=True)

        def post(self):
            route = urlparse(self.path).path
            if route == '/api/explore/tools':
                return self.run_tool()
            if not self.api_allowed():
                return self.send(403, {"error": "不允许的来源或会话"})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.send(415, {"error": "需要 JSON 请求"})
            if route not in ("/api/project", "/api/select-directory", "/api/code/query") and not agent_route(route) and not exploration_route(route):
                return self.send(404, {"error": "接口不存在"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > (65536 if exploration_route(route) else 16384):
                    return self.send(413, {"error": "请求大小无效"})
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("请求必须是对象")
                if exploration_route(route):
                    with lock:
                        current = state['data']
                    status, result = exploration_dispatch(exploration(), 'POST', route, current, body)
                    return self.send(status, result)
                if agent_route(route):
                    status, result = agent_dispatch(agents, "POST", route, body)
                    return self.send(status, result)
                if route == "/api/code/query":
                    with lock:
                        current, session = state['data'], state['code']
                    if not current or not session:
                        return self.send(422, {"error": "请先打开本地项目"})
                    if body.get('snapshotId') != current['snapshot']['id']:
                        return self.send(409, {"error": "源码快照已变化，请重新选择对象", "snapshotId": current['snapshot']['id']})
                    result = session.query(body)
                    with lock:
                        if state['code'] is not session:
                            return self.send(409, {"error": "项目已切换，请重新选择对象"})
                    return self.send(202 if result['status'] == 'building' else 200, result)
                if route == "/api/select-directory":
                    if not picker_lock.acquire(blocking=False):
                        return self.send(409, {"error": "请先完成当前的文件夹选择。"})
                    try:
                        selected = choose_directory(body.get("path"))
                    finally:
                        picker_lock.release()
                    return self.send(200, {"path": selected})
                project_path = body.get("path")
                mapping_path = body.get("mapping") or None
                if (
                    not isinstance(project_path, str)
                    or not Path(project_path).expanduser().is_absolute()
                ):
                    raise ValueError("请输入项目目录的绝对路径")
                if mapping_path is not None and not isinstance(mapping_path, str):
                    raise ValueError("映射文件路径无效")
                # Serialize scan and commit: a failed scan leaves the current project intact.
                with lock:
                    data, code = scan_inputs(project_path, mapping_path)
                    state.update(project=project_path, mapping=mapping_path, data=data, code=code)
                    if dev:
                        dev['save'](project_path, mapping_path)
                if server.exploration:
                    server.exploration.check_project(project_path)
                return self.send(200, data)
            except DirectoryPickerUnavailable as exc:
                return self.send(503, {"error": str(exc)})
            except (OSError, ValueError) as exc:
                return self.send(422, {"error": str(exc)})
            except Exception:
                return self.send(500, {"error": "扫描失败，当前项目未改变"})

        def run_tool(self):
            # Child MCP/Pi bridges use a per-run capability, never the browser token.
            if not self.allowed_host() or self.headers.get('Origin') is not None or server.exploration is None:
                return self.send(403, dict(error='工具会话无效'))
            try:
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    return self.send(415, dict(error='需要 JSON 请求'))
                length = int(self.headers.get('Content-Length', '0'))
                if not 1 <= length <= 131072:
                    return self.send(413, dict(error='工具请求过大'))
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError('工具参数无效')
                result = server.exploration.tool(body.get('runId'), self.headers.get('X-Code-Strata-Run', ''),
                                                 body.get('name'), body.get('arguments'))
                return self.send(200, result)
            except PermissionError as exc:
                return self.send(403, dict(error=str(exc)))
            except (ValueError, LookupError, TypeError) as exc:
                return self.send(422, dict(error=str(exc)))
            except Exception:
                return self.send(500, dict(error='工具执行失败；原图已保留'))

    class BoardServer(ThreadingHTTPServer):
        def begin_reload(self):
            with self.reload_lock:
                self.draining = True

        def reload_idle(self):
            with self.reload_lock:
                if self.active_requests:
                    return False
                with agents.lock:
                    if any(j['result']['status'] == 'running' for j in agents.tests.values()):
                        return False
                if self.exploration:
                    with self.exploration.lock:
                        if any(not j['done'].is_set() for j in self.exploration.jobs.values()):
                            return False
                return True

        def server_close(self):
            if getattr(self, 'exploration', None):
                self.exploration.close()
            agents.close()
            super().server_close()

    server = BoardServer(("127.0.0.1", port), Handler)
    server.agents = agents
    server.exploration = None
    server.reload_lock = Lock()
    server.draining, server.active_requests = False, 0
    return server


def port_number(value):
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("端口必须是 0–65535 的整数") from None
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("端口必须在 0–65535 之间；0 表示自动选择")
    return port


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--project", help="初次打开的项目目录；省略时使用示例")
    cli.add_argument("--mapping", help="可选的架构映射 JSON，显式指定")
    cli.add_argument("--node", help="可选的 Node 可执行文件路径")
    cli.add_argument("--scc", help="scc 可执行文件路径")
    cli.add_argument("--work-dir", help="捕获文件的短生命周期工作目录")
    cli.add_argument("--history-db", help="Agent 探索历史 SQLite 路径；默认 XDG 数据目录")
    cli.add_argument("--dev", action="store_true", help="开发模式：前端热更新、后端自动重载，等待当前 Agent 任务结束")
    cli.add_argument(
        "--port", type=port_number, default=DEFAULT_PORT,
        help=f"监听端口，默认 {DEFAULT_PORT}；传 0 自动选择空闲端口",
    )
    cli.add_argument("--open", action="store_true", help="在系统默认浏览器打开")
    args = cli.parse_args(argv)
    if args.dev:
        from dev import run
        try:
            return run(args)
        except (OSError, ValueError, SyntaxError) as exc:
            cli.exit(1, f'{exc}\n')
    dev = None
    if os.environ.get('CODE_STRATA_DEV_STATE'):
        from dev import write_state
        state_path = Path(os.environ['CODE_STRATA_DEV_STATE'])
        if state_path.exists():
            saved = json.loads(state_path.read_text())
            args.project, args.mapping = saved['project'], saved['mapping']
        dev = dict(token=os.environ['CODE_STRATA_DEV_TOKEN'], frontend=os.environ['CODE_STRATA_DEV_FRONTEND'],
                   save=lambda project, mapping: write_state(state_path, dict(project=project, mapping=mapping)))
    try:
        server = make_server(
            args.project, args.mapping, args.node, args.port, args.scc, args.work_dir, history_path=args.history_db,
            **({'dev': dev} if dev else {})
        )
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            cli.exit(
                1,
                f"端口 {args.port} 已被占用。请关闭占用该端口的服务，"
                "或通过 --port 指定其他端口（--port 0 自动选择）。\n",
            )
        cli.exit(1, f"{exc}\n")
    except ValueError as exc:
        cli.exit(1, f"{exc}\n")
    url = f"http://127.0.0.1:{server.server_port}"
    print(
        json.dumps({"url": url, "mode": "read-only", "project": args.project}, ensure_ascii=False),
        flush=True,
    )
    if args.open:
        webbrowser.open(url)
    previous_term = signal.getsignal(signal.SIGTERM)
    def stop_service(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop_service)
    control = None
    if dev:
        from dev import ReloadControl
        dev['save'](args.project, args.mapping)
        control = ReloadControl(server, Path(os.environ['CODE_STRATA_DEV_RELOAD']))
        control.thread.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if control:
                control.close()
            server.server_close()
        finally:
            signal.signal(signal.SIGTERM, previous_term)
    if control and control.ready:
        from dev import RELOAD_EXIT
        return RELOAD_EXIT


if __name__ == "__main__":
    raise SystemExit(main())
