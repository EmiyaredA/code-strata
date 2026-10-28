"""Local development supervisor: Vite HMR and graceful Python reloads."""
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import ProxyHandler, build_opener

from node_runtime import resolve_node

ROOT = Path(__file__).resolve().parent.parent
RELOAD_EXIT = 75
SOURCE_SUFFIXES = {'.py', '.cjs', '.mjs', '.js', '.ts', '.json'}


def revision(root=ROOT / 'scripts'):
    result = {}
    for path in root.rglob('*'):
        if path.suffix in SOURCE_SUFFIXES and '__pycache__' not in path.parts:
            try:
                stat = path.stat()
                result[str(path)] = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
            except FileNotFoundError:
                pass
    return result


def validate_python(paths):
    """Leave the working backend alive while an edit contains a syntax error."""
    for name in sorted(paths):
        path = Path(name)
        if path.suffix == '.py' and path.is_file():
            compile(path.read_bytes(), name, 'exec')


def available_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def stop_process(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def write_state(path, state):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, ensure_ascii=False))
    os.chmod(temporary, 0o600)
    temporary.replace(path)


class ReloadControl:
    """The child drains requests and Agent tasks before releasing its DB lock."""
    def __init__(self, server, request_path, source_root=ROOT / 'scripts'):
        self.server, self.request_path = server, request_path
        self.source_root = source_root
        self.stop = threading.Event()
        self.ready = False
        self.thread = threading.Thread(target=self._watch, daemon=True)

    def _watch(self):
        checked, valid = None, False
        while not self.stop.wait(.15):
            if not self.request_path.exists():
                continue
            # More edits can arrive while a long Agent task drains. Recheck the
            # latest source before shutting down the still-working process.
            latest = revision(self.source_root)
            if latest != checked:
                checked = latest
                try:
                    validate_python(latest)
                    valid = True
                except (SyntaxError, UnicodeError, OSError):
                    valid = False
            if not valid:
                continue
            self.server.begin_reload()
            if self.server.reload_idle():
                self.ready = True
                self.server.shutdown()
                return

    def close(self):
        self.stop.set()
        self.thread.join(timeout=2)


def backend_command(args, port):
    command = [sys.executable, '-B', '-u', str(ROOT / 'scripts/serve.py'), '--port', str(port)]
    for name in ('project', 'mapping', 'node', 'scc', 'work_dir', 'history_db'):
        value = getattr(args, name, None)
        if value:
            command.extend(['--' + name.replace('_', '-'), str(value)])
    return command


def run(args, *, watch_root=None):
    frontend = ROOT / 'assets/board-source'
    vite_cli = frontend / 'node_modules/vite/bin/vite.js'
    if not vite_cli.is_file():
        raise ValueError('开发模式需要前端依赖，请先在 assets/board-source 运行 npm ci')
    node = resolve_node(args.node)
    if node['status'] != 'ready':
        raise ValueError(node['message'])
    port = args.port or available_port()
    vite_port = available_port()
    while vite_port == port:
        vite_port = available_port()
    url = f'http://127.0.0.1:{port}'
    vite_url = f'http://127.0.0.1:{vite_port}'
    stop = threading.Event()
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    for sig in previous:
        signal.signal(sig, lambda *_: stop.set())
    vite = backend = None
    try:
        with tempfile.TemporaryDirectory(prefix='code-strata-dev-') as temporary:
            state = Path(temporary) / 'state.json'
            request = Path(temporary) / 'reload'
            env = dict(os.environ, CODE_STRATA_DEV_STATE=str(state), CODE_STRATA_DEV_RELOAD=str(request),
                       CODE_STRATA_DEV_TOKEN=os.environ.get('CODE_STRATA_DEV_TOKEN') or secrets.token_urlsafe(32), CODE_STRATA_DEV_FRONTEND=vite_url,
                       CODE_STRATA_DEV_VITE_PORT=str(vite_port), PYTHONDONTWRITEBYTECODE='1')
            vite = subprocess.Popen([node['executable'], str(vite_cli), '--host', '127.0.0.1',
                                     '--port', str(vite_port), '--strictPort'], cwd=frontend, env=env,
                                    start_new_session=True)
            opener = build_opener(ProxyHandler({}))
            deadline = time.monotonic() + 20
            while not stop.is_set():
                if vite.poll() is not None:
                    raise ValueError('Vite 启动失败，请查看上方日志')
                try:
                    with opener.open(vite_url + '/@vite/client', timeout=.5):
                        break
                except OSError:
                    if time.monotonic() > deadline:
                        raise ValueError('等待 Vite 启动超时')
                    stop.wait(.1)
            if stop.is_set():
                return 0
            watched = Path(watch_root) if watch_root is not None else ROOT / 'scripts'
            current = revision(watched)
            validate_python(current)
            backend = subprocess.Popen(backend_command(args, port), env=env, start_new_session=True)
            pending_at, requested, opened = None, False, False
            print(f'[dev] {url} · 前端热更新 / Python 自动重载；Agent 运行期间延后重载', flush=True)
            while not stop.wait(.15):
                if vite.poll() is not None:
                    raise ValueError('Vite 已退出，开发服务停止')
                if args.open and not opened and state.exists():
                    import webbrowser
                    webbrowser.open(url)
                    opened = True
                code = backend.poll()
                if code is not None:
                    if code != RELOAD_EXIT:
                        return code
                    request.unlink(missing_ok=True)
                    backend = subprocess.Popen(backend_command(args, port), env=env, start_new_session=True)
                    requested = False
                    print('[dev] 后端已自动重载，页面和会话保持原位', flush=True)
                latest = revision(watched)
                if latest != current:
                    current, pending_at = latest, time.monotonic()
                if pending_at is not None and time.monotonic() - pending_at >= .6:
                    pending_at = None
                    try:
                        validate_python(current)
                    except (SyntaxError, UnicodeError, OSError) as exc:
                        print(f'[dev] 暂不重载，继续使用上个版本：{exc}', file=sys.stderr, flush=True)
                        continue
                    if not requested:
                        request.touch(mode=0o600)
                        requested = True
                        print('[dev] 检测到后端改动，等待当前请求和 Agent 任务结束后重载…', flush=True)
            return 0
    finally:
        stop_process(backend)
        stop_process(vite)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
