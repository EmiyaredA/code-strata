"""scc adapter; only counts captured immutable files and never estimates."""

import json
import platform
import shutil
import subprocess
from pathlib import Path


def find_scc(explicit=None):
    if explicit:
        return (
            str(Path(explicit).expanduser().resolve())
            if "/" in explicit or "\\" in explicit
            else shutil.which(explicit) or explicit
        )
    bundled = (
        Path(__file__).parent.parent
        / "assets"
        / "tools"
        / f"{platform.system().lower()}-{platform.machine().lower()}"
        / "scc"
    )
    return str(bundled) if bundled.is_file() else shutil.which("scc")


def count_files(stage, entries, executable=None):
    tool = find_scc(executable)
    report = dict(
        name="scc", version=None, status="unavailable", message="代码行数未采集：scc 不可用"
    )
    candidates = [
        x for x in entries if x["category"] != "config" and x["captureStatus"] == "captured"
    ]
    for item in candidates:
        item["countStatus"] = "unavailable"
    if not tool:
        return report
    try:
        report["version"] = subprocess.run(
            [tool, "--version"], text=True, capture_output=True, timeout=10, check=True
        ).stdout.strip()
        result = subprocess.run(
            [
                tool,
                "--by-file",
                "--format",
                "json",
                "--no-complexity",
                "--no-cocomo",
                "--no-ignore",
                "--no-gitignore",
                "--no-config",
                ".",
            ],
            cwd=stage,
            text=True,
            capture_output=True,
            timeout=90,
            check=True,
        )
        rows = json.loads(result.stdout)
        by_path = {x["id"]: x for x in candidates}
        for group in rows:
            for row in group.get("Files", []):
                path = Path(row["Location"]).as_posix().removeprefix("./")
                if path not in by_path:
                    continue
                item = by_path[path]
                item.update(
                    countStatus="counted",
                    metrics=dict(
                        code=row["Code"],
                        comments=row["Comment"],
                        blanks=row["Blank"],
                        lines=row["Lines"],
                    ),
                    counterLanguage=group["Name"],
                )
        for item in candidates:
            if item["countStatus"] != "counted":
                item.update(countStatus="unsupported", countReason="scc 未返回该文件；未按零行处理")
        report.update(status="ready", message=None)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        for item in candidates:
            item.update(countStatus="unavailable", metrics=None)
        report.update(
            status="unavailable", message=f"代码行数未采集：scc 执行失败（{type(exc).__name__}）"
        )
    return report


def aggregate(items, tool):
    items = list({x["id"]: x for x in items}.values())
    counted = [x for x in items if x["countStatus"] == "counted"]
    return dict(
        files=len(items),
        countedFiles=len(counted),
        status="unavailable"
        if tool["status"] != "ready"
        else "complete"
        if len(items) == len(counted)
        else "partial",
        **{
            key: sum(x["metrics"][key] for x in counted)
            if tool["status"] == "ready" and (counted or not items)
            else None
            for key in ("code", "comments", "blanks", "lines")
        },
    )


def summarize(entries, tool):
    source = [x for x in entries if x["category"] != "config"]
    categories = {
        c: aggregate([x for x in source if x["category"] == c], tool)
        for c in ("source", "test", "generated", "third-party")
    }
    languages = {
        v: aggregate([x for x in source if x["language"] == v], tool)
        for v in sorted({x["language"] for x in source})
    }
    directories = {
        v: aggregate([x for x in source if str(Path(x["path"]).parent) == v], tool)
        for v in sorted({str(Path(x["path"]).parent) for x in source})
    }
    return dict(
        tool=tool,
        categories=categories,
        languages=languages,
        directories=directories,
        total=aggregate(source, tool),
    )
