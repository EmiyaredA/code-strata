"""Shared, immutable input inventory and deterministic file classification."""

import hashlib
import os
import re
import subprocess
from pathlib import Path

PARSER_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"}
LANGUAGES = {
    **{x: "typescript" for x in (".ts", ".tsx", ".mts", ".cts")},
    **{x: "javascript" for x in (".js", ".jsx", ".mjs", ".cjs")},
    ".py": "python",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".vue": "vue",
    ".svelte": "svelte",
    ".css": "css",
    ".scss": "scss",
    ".less": "less",
    ".html": "html",
    ".sql": "sql",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".ps1": "powershell",
    ".dart": "dart",
    ".ex": "elixir",
    ".exs": "elixir",
    ".lua": "lua",
    ".r": "r",
    ".m": "objective-c",
    ".scala": "scala",
    ".clj": "clojure",
    ".pl": "perl",
}
EXCLUDED = {
    ".git",
    ".local",
    ".runtime",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    "coverage",
    ".next",
    ".cache",
    ".tox",
    ".mypy_cache",
}
CONFIG_NAMES = {
    "package.json",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "pyproject.toml",
    "uv.lock",
    "requirements.txt",
    ".nvmrc",
    ".node-version",
    ".python-version",
}
MAX_FILES, MAX_FILE_SIZE, MAX_TOTAL = 50000, 16 * 1024 * 1024, 256 * 1024 * 1024
RULES = {
    "version": 1,
    "precedence": ["third-party", "generated", "test", "source"],
    "thirdParty": ["vendor", "third_party", "third-party"],
    "test": [
        "test",
        "tests",
        "e2e",
        "__tests__",
        "fixtures",
        "*.test.*",
        "*.spec.*",
        "test_*.py",
        "*_test.py",
    ],
    "generated": [
        "generated",
        "__generated__",
        "*.generated.*",
        "do not edit",
        "auto-generated",
        "@generated",
    ],
    "default": "source（当前规则下的自有源码，不是作者或版权判定）",
}


def git(root, *args):
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, timeout=15, check=True
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def stamp(path):
    s = path.stat()
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)


def is_config(name):
    return name in CONFIG_NAMES or (name.startswith("tsconfig") and name.endswith(".json"))


def classify(path, content):
    parts = Path(path).parts
    if any(x in RULES["thirdParty"] for x in parts):
        return "third-party", "目录：vendor / third_party / third-party"
    if any(x in ("generated", "__generated__") for x in parts) or ".generated." in path:
        return "generated", "生成目录或 *.generated.* 文件名"
    if re.search(r"do not edit|auto[- ]generated|@generated", content[:2048], re.I):
        return "generated", "文件头生成标记（前 2048 字符）"
    name = Path(path).name
    if (
        any(x in RULES["test"][:6] for x in parts)
        or re.search(r"\.(test|spec)\.", name)
        or name.startswith("test_")
        and name.endswith(".py")
        or name.endswith("_test.py")
    ):
        return "test", "测试目录、夹具或测试文件名"
    return "source", RULES["default"]


def discover(root):
    listed = git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", ".")
    if listed == b"":
        top = git(root, "rev-parse", "--show-toplevel")
        if top is not None and Path(os.fsdecode(top).strip()).resolve() != root:
            listed = None
    if listed is not None:
        return sorted({os.fsdecode(x) for x in listed.split(b"\0") if x})
    paths = []
    for current, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED and not Path(current, d).is_symlink())
        paths.extend((Path(current, n).relative_to(root)).as_posix() for n in sorted(names))
    return sorted(paths)


def capture(root, stage):
    entries, configs, originals, notes = [], {}, {}, []
    total, parser_total, parser_count = 0, 0, 0
    for path in discover(root):
        rel = Path(path)
        if rel.is_absolute() or ".." in rel.parts or any(p in EXCLUDED for p in rel.parts):
            continue
        if rel.name.startswith(".env") or rel.name.endswith((".min.js", ".min.css")):
            continue
        config, language = is_config(rel.name), LANGUAGES.get(rel.suffix.lower())
        if not config and not language:
            continue
        item = dict(
            id=path,
            path=path,
            language=language,
            category="config" if config else "source",
            classificationRule="配置输入" if config else "",
            size=None,
            hash=None,
            captureStatus="pending",
            parseStatus="not-applicable" if config else "unsupported",
            countStatus="not-applicable" if config else "pending",
            metrics=None,
        )
        entries.append(item)
        source = root / rel
        try:
            if any(
                (root / Path(*rel.parts[:i])).is_symlink() for i in range(1, len(rel.parts) + 1)
            ):
                raise ValueError("符号链接不读取")
            before = stamp(source)
            item["size"] = before[2]
            if (
                len(entries) > MAX_FILES
                or total + before[2] > MAX_TOTAL
                or before[2] > MAX_FILE_SIZE
            ):
                raise ValueError("超过盘点读取预算（5 万文件 / 单文件 16 MiB / 总计 256 MiB）")
            raw = source.read_bytes()
            if stamp(source) != before:
                raise ValueError("读取期间文件变化，待重扫")
            text = raw.decode("utf-8")
            if "\0" in text:
                raise ValueError("不是可分析的文本文件")
            total += len(raw)
            item.update(hash=hashlib.sha256(raw).hexdigest(), captureStatus="captured")
            originals[path] = before
            if config:
                configs[path] = text
            else:
                category, rule = classify(path, text)
                item.update(category=category, classificationRule=rule)
                target = stage / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
                if rel.suffix in PARSER_EXTENSIONS:
                    if (
                        len(raw) > 512 * 1024
                        or parser_count >= 5000
                        or parser_total + len(raw) > 32 * 1024 * 1024
                    ):
                        item.update(
                            parseStatus="skipped",
                            parseReason=(
                                "超过引用解析预算：5000 文件 / 单文件 512 KiB / 总计 32 MiB"
                            ),
                        )
                    else:
                        item.update(parseStatus="pending", content=text, symbols=[])
                        parser_count += 1
                        parser_total += len(raw)
                else:
                    item["parseReason"] = "该语言暂不支持引用解析"
        except (OSError, ValueError, UnicodeError) as exc:
            item.update(
                captureStatus="skipped",
                captureReason=str(exc),
                countStatus="skipped",
                parseStatus="skipped",
            )
            notes.append(dict(kind="coverage", path=path, message=str(exc)))
    return entries, configs, originals, notes


def verify_inputs(root, entries, originals):
    """Invalidate changed inputs; downstream output must discard their conclusions."""
    changed = []
    for item in entries:
        if item["captureStatus"] != "captured":
            continue
        try:
            path = root / item["id"]
            rel = Path(item["id"])
            if (
                any(
                    (root / Path(*rel.parts[:i])).is_symlink() for i in range(1, len(rel.parts) + 1)
                )
                or stamp(path) != originals[item["id"]]
                or hashlib.sha256(path.read_bytes()).hexdigest() != item["hash"]
                or stamp(path) != originals[item["id"]]
            ):
                raise ValueError("扫描期间文件变化，待重扫")
        except (OSError, ValueError):
            item.update(
                captureStatus="changed", parseStatus="changed", countStatus="changed", metrics=None
            )
            changed.append(item["id"])
    return changed
