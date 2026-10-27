"""Bounded tool process runner with raw logs and process-tree memory sampling."""

import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import time


def tool_environment(java, work):
    java = Path(java).resolve()
    work = Path(work).resolve()
    home, temporary = work / "jvm-home", work / "tmp"
    home.mkdir(parents=True, exist_ok=True)
    temporary.mkdir(exist_ok=True)
    env = os.environ.copy()
    env["JAVA_HOME"] = str(java.parent.parent)
    env["PATH"] = str(java.parent) + os.pathsep + env.get("PATH", "")
    if os.uname().sysname == "Darwin" and not shutil.which('greadlink'):
        probe_path=Path(__file__).resolve()
        check=subprocess.run(['/usr/bin/readlink','-f',str(probe_path)],capture_output=True,text=True,check=True)
        if check.stdout.strip() != str(probe_path):
            raise ValueError('System readlink -f does not meet the packaged launcher contract')
        compatibility=work/'compat-bin'
        compatibility.mkdir(exist_ok=True)
        link=compatibility/'greadlink'
        if not link.exists():
            link.symlink_to('/usr/bin/readlink')
        env['PATH']=str(compatibility)+os.pathsep+env['PATH']
    options = f"-Xmx4g -Duser.home={home} -Djava.io.tmpdir={temporary}"
    env["JAVA_OPTS"] = options
    env["_JAVA_OPTIONS"] = options
    env.pop("JDK_JAVA_OPTIONS", None)
    if os.uname().sysname == "Darwin":
        env["CODESTRATA_JOERN_OFFLINE"] = "1"
    return env


def tree_rss(pid):
    try:
        listing = subprocess.run(["ps", "-axo", "pid=,ppid=,rss="], capture_output=True, text=True, timeout=2)
        if listing.returncode:
            return None
        rows = [tuple(map(int,line.split())) for line in listing.stdout.splitlines() if len(line.split()) == 3]
        descendants = {pid}
        while True:
            more = {p for p,parent,_ in rows if parent in descendants}
            if more <= descendants:
                break
            descendants |= more
        return sum(rss for p,_,rss in rows if p in descendants) * 1024
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def run_process(command, cwd, env, log, timeout=600, use_system_time=True):
    command = [str(x) for x in command]
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    timed_out, peak, memory_samples = False, 0, 0
    offline = env.get("CODESTRATA_JOERN_OFFLINE") == "1"
    wrapped = ["/usr/bin/sandbox-exec", "-p", "(version 1)(allow default)(deny network*)", *command] if offline else command
    if use_system_time and os.uname().sysname == "Darwin":
        wrapped = ["/usr/bin/time", "-l", *wrapped]
    with log.open("w") as stream:
        try:
            process = subprocess.Popen(wrapped, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as exc:
            stream.write(str(exc))
            return dict(command=command, status="unavailable", error=str(exc), log=str(log), seconds=time.monotonic()-started)
        try:
            while process.poll() is None:
                if time.monotonic() - started > timeout:
                    timed_out = True
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                    break
                rss = tree_rss(process.pid)
                if rss is not None:
                    peak, memory_samples = max(peak, rss), memory_samples + 1
                time.sleep(.5)
        except BaseException:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise
        process.wait()
    text = log.read_text(errors="replace")
    match = re.search(r"(\d+)\s+maximum resident set size", text)
    return dict(command=command, status="timeout" if timed_out else "complete" if process.returncode == 0 else "failed",
                networkIsolation="macOS deny network*" if offline else "not-enforced-by-runner",
                returncode=process.returncode, seconds=round(time.monotonic()-started,3), log=str(log),
                peakRSSBytes=int(match[1]) if match else None,
                processTreePeakRSSBytes=peak if memory_samples else None,
                memorySampling="sampled process-tree RSS; shared pages can be counted more than once" if memory_samples else "unavailable")
