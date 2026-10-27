"""Select a local directory without reading or scanning its contents."""

from pathlib import Path
import subprocess
import sys


class DirectoryPickerUnavailable(RuntimeError):
    pass


# Pass the initial directory as an argument, never interpolate it into code.
MAC_PICKER = '''on run argv
    try
        activate
        if (count of argv) > 0 then
            set initialFolder to POSIX file (item 1 of argv)
            set selectedFolder to choose folder with prompt "选择项目文件夹" default location initialFolder
        else
            set selectedFolder to choose folder with prompt "选择项目文件夹"
        end if
        return POSIX path of selectedFolder
    on error number -128
        return ""
    end try
end run'''

# Tk must run on the child process's main thread, not an HTTP worker thread.
TK_PICKER = '''import sys
import tkinter as tk
from tkinter import filedialog
root = tk.Tk()
root.withdraw()
try:
    print(filedialog.askdirectory(parent=root, title="选择项目文件夹",
        initialdir=sys.argv[1] or None, mustexist=True) or "")
finally:
    root.destroy()
'''


def choose_directory(initial=None):
    if initial is not None and not isinstance(initial, str):
        raise ValueError("项目目录必须是字符串")
    initial_path = Path(initial).expanduser() if initial else None
    if initial_path is not None and not initial_path.is_absolute():
        raise ValueError("请输入项目目录的绝对路径")
    start = str(initial_path) if initial_path and initial_path.is_dir() else ""
    if sys.platform == "darwin":
        command = ["/usr/bin/osascript", "-e", MAC_PICKER]
        if start:
            command.append(start)
    else:
        command = [sys.executable, "-c", TK_PICKER, start]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=True, timeout=120
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise DirectoryPickerUnavailable(
            "无法打开系统文件夹选择器，请手动输入目录绝对路径。"
        ) from exc
    selected = result.stdout.rstrip("\r\n")
    if not selected:
        return None
    path = Path(selected)
    if not path.is_absolute() or not path.is_dir():
        raise DirectoryPickerUnavailable("选择的文件夹已不可用，请重新选择。")
    return str(path)
