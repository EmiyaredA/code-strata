"""Locate a runnable Node.js 18+ without installing or executing project code."""

import os
from pathlib import Path
import re
import shutil
import subprocess


def resolve_node(explicit=None):
    if explicit:
        candidates = [shutil.which(explicit) or str(Path(explicit).expanduser())]
    else:
        name = "node.exe" if os.name == "nt" else "node"
        candidates = [str(Path(directory) / name) for directory in os.get_exec_path()]
    seen = set()
    for candidate in candidates:
        path = Path(candidate).resolve()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            result = subprocess.run(
                [str(path), "--version"], capture_output=True, text=True, timeout=5, check=True
            )
            version = result.stdout.strip()
            match = re.fullmatch(r"v(\d+)\.\d+\.\d+(?:[-+].*)?", version)
            if match and int(match[1]) >= 18:
                return dict(status="ready", executable=str(path), version=version)
        except (OSError, subprocess.SubprocessError):
            continue
    return dict(
        status="unavailable", executable=None, version=None,
        message="未找到可运行的 Node.js 18+；请使用 --node 指定可用的 Node 可执行文件。",
    )
