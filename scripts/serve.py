"""Serve the local, read-only architecture board. Requires Python 3.10+."""

import argparse
import json
import mimetypes
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

from scan import scan_project
from code_analysis.service import CodeSession
from directory_picker import choose_directory, DirectoryPickerUnavailable

ASSETS = Path(__file__).resolve().parent.parent / "assets" / "board"


def make_server(project=None, mapping=None, node=None, port=0, scc=None, work_dir=None):
    token = secrets.token_urlsafe(32)
    state = dict(project=None, mapping=None, data=None, code=None)
    lock = Lock()
    picker_lock = Lock()
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

        def do_GET(self):
            if not self.allowed_host():
                return self.send(403, {"error": "不允许的来源"})
            path = urlparse(self.path).path
            if path == "/api/project":
                if not self.api_allowed():
                    return self.send(403, {"error": "看板会话无效，请刷新页面"})
                with lock:
                    return self.send(200, state["data"] or {"demo": True})
            if path.startswith("/api/"):
                return self.send(404, {"error": "接口不存在"})
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

        def do_POST(self):
            if not self.api_allowed():
                return self.send(403, {"error": "不允许的来源或会话"})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.send(415, {"error": "需要 JSON 请求"})
            route = urlparse(self.path).path
            if route not in ("/api/project", "/api/select-directory", "/api/code/query"):
                return self.send(404, {"error": "接口不存在"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 16384:
                    return self.send(413, {"error": "请求大小无效"})
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("请求必须是对象")
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
                return self.send(200, data)
            except DirectoryPickerUnavailable as exc:
                return self.send(503, {"error": str(exc)})
            except (OSError, ValueError) as exc:
                return self.send(422, {"error": str(exc)})
            except Exception:
                return self.send(500, {"error": "扫描失败，当前项目未改变"})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--project", help="初次打开的项目目录；省略时使用示例")
    cli.add_argument("--mapping", help="可选的架构映射 JSON，显式指定")
    cli.add_argument("--node", help="可选的 Node 可执行文件路径")
    cli.add_argument("--scc", help="scc 可执行文件路径")
    cli.add_argument("--work-dir", help="捕获文件的短生命周期工作目录")
    cli.add_argument("--port", type=int, default=0)
    cli.add_argument("--open", action="store_true", help="在系统默认浏览器打开")
    args = cli.parse_args()
    try:
        server = make_server(
            args.project, args.mapping, args.node, args.port, args.scc, args.work_dir
        )
    except (OSError, ValueError) as exc:
        cli.exit(1, f"{exc}\n")
    url = f"http://127.0.0.1:{server.server_port}"
    print(
        json.dumps({"url": url, "mode": "read-only", "project": args.project}, ensure_ascii=False),
        flush=True,
    )
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
