"""Bounded subprocess I/O, executable discovery and process-tree ownership."""
from collections import deque
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import threading
import time

from node_runtime import resolve_node


class AgentError(Exception):
    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


def redact(text):
    for key, value in os.environ.items():
        if len(value) >= 6 and re.search(r"(?i)(api.?key|token|password|secret|credential)", key):
            text = text.replace(value, "[hidden]")
    text = re.sub(r"(?i)(Bearer\s+)[^\s\"']+", r"\1[hidden]", text)
    text = re.sub(r"(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|authorization)[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+", r"\1[hidden]", text)
    text = re.sub(r"\b(?:sk|sk-ant)-[A-Za-z0-9_-]{8,}", "[hidden]", text)
    return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)


def search_directories():
    home = Path.home()
    extras = [home / ".local/bin", home / ".npm-global/bin", home / ".bun/bin",
              home / ".volta/bin", home / ".asdf/shims", "/opt/homebrew/bin", "/usr/local/bin"]
    for pattern in (".nvm/versions/node/*/bin", ".local/share/fnm/node-versions/*/installation/bin"):
        extras.extend(sorted(home.glob(pattern), reverse=True)[:12])
    return list(dict.fromkeys(str(p) for p in [*os.get_exec_path(), *extras] if str(p)))


def resolve_launch(definition, config, node=None):
    directories = search_directories()
    explicit = config["executablePath"]
    candidates = [Path(explicit)] if explicit else [Path(d) / name for name in definition.bins for d in directories]
    if not explicit and definition.id == "codex":
        for root in (Path.home() / "Applications", Path("/Applications")):
            candidates.extend([root / "Codex.app/Contents/Resources/codex",
                               root / "ChatGPT.app/Contents/Resources/codex-cli/bin/codex"])
    for path in candidates:
        if not path.is_file() or not os.access(path, os.X_OK):
            continue
        env = dict(os.environ)
        env["PATH"] = os.pathsep.join(directories)
        env["NO_COLOR"] = "1"
        command = [str(path)]
        try:
            with path.open("rb") as stream:
                shebang = stream.readline(256).decode("utf-8", "replace")
            if shebang.startswith("#!") and re.search(r"(?:/|\s)node(?:\s|$)", shebang):
                runtime = resolve_node(node)
                if runtime["status"] != "ready" and not node:
                    for directory in directories:
                        candidate = Path(directory) / ("node.exe" if os.name == "nt" else "node")
                        if candidate.is_file():
                            runtime = resolve_node(str(candidate))
                            if runtime["status"] == "ready":
                                break
                if runtime["status"] != "ready":
                    raise AgentError("launch", "CLI 已找到，但缺少可运行的 Node；可通过服务的 --node 参数指定")
                command = [runtime["executable"], str(path.resolve())]
                env["PATH"] = os.pathsep.join(dict.fromkeys([str(Path(runtime["executable"]).parent), *directories]))
        except OSError as exc:
            raise AgentError("launch", str(exc)) from exc
        return {"path": str(path), "command": command, "env": env}
    if explicit:
        raise AgentError("launch", "指定的可执行文件不存在或没有执行权限；请修改路径或清空以自动检测")
    raise AgentError("not_found", "未找到本地 CLI，可填写可执行文件的绝对路径")


class Process:
    def __init__(self, launch, args, cwd, cancel, timeout, *, max_output=262144, max_line=65536):
        self.cancel, self.deadline = cancel, time.monotonic() + timeout
        self.max_output, self.max_line = max_output, max_line
        self.reader_stop = threading.Event()
        self.events = queue.Queue(maxsize=1024)
        self.logs = {"stdout": deque(maxlen=80), "stderr": deque(maxlen=80)}
        self.total, self.overflow, self.eof = 0, threading.Event(), set()
        self.count_lock = threading.Lock()
        self.write_lock = threading.Lock()
        try:
            self.child = subprocess.Popen([*launch["command"], *args], cwd=cwd, env=launch["env"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=os.name != "nt",
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
        except OSError as exc:
            raise AgentError("launch", f"无法启动 CLI：{exc}") from exc
        self.readers = []
        for name in ("stdout", "stderr"):
            thread = threading.Thread(target=self._pump, args=(name,), daemon=True)
            thread.start()
            self.readers.append(thread)

    def _pump(self, name):
        stream = getattr(self.child, name)
        try:
            while True:
                line = stream.readline(self.max_line + 1)
                if not line:
                    break
                with self.count_lock:
                    self.total += len(line)
                    exceeded = self.total > self.max_output or len(line) > self.max_line
                if exceeded:
                    self.overflow.set()
                    break
                value = line.decode("utf-8", "replace")
                with self.count_lock:
                    self.logs[name].append(value[-8192:])
                if not self._enqueue((name, value)):
                    break
        finally:
            self._enqueue((name, None))

    def _enqueue(self, event):
        while not self.reader_stop.is_set():
            try:
                self.events.put(event, timeout=.1)
                return True
            except queue.Full:
                continue
        return False

    def check(self):
        if self.cancel.is_set():
            raise AgentError("cancelled", "测试已取消")
        if time.monotonic() >= self.deadline:
            raise AgentError("timeout", "连接测试超时，请检查 CLI 登录、模型配置和网络")
        if self.overflow.is_set():
            raise AgentError("protocol", "CLI 输出超过测试限制")

    def read(self):
        self.check()
        try:
            name, line = self.events.get(timeout=.1)
        except queue.Empty:
            return None
        if line is None:
            self.eof.add(name)
            return None
        return name, line

    def send(self, text):
        with self.write_lock:
            try:
                self.child.stdin.write(text.encode())
                self.child.stdin.flush()
            except (OSError, ValueError) as exc:
                raise AgentError("protocol", "CLI 在接收请求前已退出") from exc

    def finish_input(self):
        with self.write_lock:
            self.child.stdin.close()

    def diagnostics(self):
        with self.count_lock:
            return {name: redact("".join(lines)[-8192:]) for name, lines in self.logs.items()}

    def close(self):
        self.reader_stop.set()
        # A group can outlive its leader; terminate descendants even after CLI exit.
        if os.name != "nt":
            try:
                os.killpg(self.child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError:
                if self.child.poll() is None:
                    self.child.terminate()
        elif self.child.poll() is None:
            subprocess.run(["taskkill", "/PID", str(self.child.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        try:
            self.child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                try:
                    os.killpg(self.child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except PermissionError:
                    self.child.kill()
            else:
                self.child.kill()
            self.child.wait(timeout=2)
        if os.name != "nt":
            try:
                os.killpg(self.child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError:
                pass
        for reader in self.readers:
            reader.join(timeout=1)
        for stream in (self.child.stdin, self.child.stdout, self.child.stderr):
            stream.close()
