"""Evidence-first Node/npm and Python/uv technology detection. No project execution."""

import json
import re
from pathlib import PurePosixPath

try:
    import tomllib
except ImportError:
    from _vendor import tomli as tomllib

REGISTRY = {
    "node:react": ("React", "framework", ["react"]),
    "node:vue": ("Vue", "framework", ["vue"]),
    "node:next": ("Next.js", "framework", ["next"]),
    "node:svelte": ("Svelte", "framework", ["svelte"]),
    "node:express": ("Express", "framework", ["express"]),
    "node:electron": ("Electron", "runtime", ["electron"]),
    "node:vite": ("Vite", "build", ["vite"]),
    "node:webpack": ("webpack", "build", ["webpack"]),
    "node:typescript": ("TypeScript", "language", ["typescript"]),
    "node:vitest": ("Vitest", "test", ["vitest"]),
    "node:@playwright/test": ("Playwright", "test", ["@playwright/test", "playwright"]),
    "node:jest": ("Jest", "test", ["jest"]),
    "node:better-sqlite3": ("better-sqlite3", "storage", ["better-sqlite3"]),
    "node:prisma": ("Prisma", "storage", ["prisma", "@prisma/client"]),
    "python:fastapi": ("FastAPI", "framework", ["fastapi"]),
    "python:django": ("Django", "framework", ["django"]),
    "python:flask": ("Flask", "framework", ["flask"]),
    "python:sqlalchemy": ("SQLAlchemy", "storage", ["sqlalchemy"]),
    "python:aiosqlite": ("aiosqlite", "storage", ["aiosqlite"]),
    "python:sqlite3": ("SQLite", "storage", ["sqlite3"]),
    "python:pytest": ("pytest", "test", ["pytest"]),
    "python:ruff": ("Ruff", "build", ["ruff"]),
    "python:uvicorn": ("Uvicorn", "runtime", ["uvicorn"]),
}
RULE_VERSION = 2


def line_of(text, needle):
    return next((i for i, line in enumerate(text.splitlines(), 1) if needle in line), 1)


def evidence(path, text, needle, kind, value=None, selector=None):
    line = line_of(text, needle)
    return dict(
        path=path,
        line=line,
        kind=kind,
        value=value,
        selector=selector,
        text=text.splitlines()[line - 1].strip()[:300] if text.splitlines() else "",
    )


def locked_evidence(path, text, package, version, location=None):
    """Find the version line in its specific JSON record or TOML package block."""
    if location is not None:
        start = text.find(json.dumps(location))
        fragment = text[start:] if start >= 0 else ""
        match = re.search(r'"version"\s*:\s*"' + re.escape(version) + '"', fragment)
        offset = start + match.start() if match else max(start, 0)
    else:
        offset = 0
        for match in re.finditer(r"^\[\[package\]\].*?(?=^\[\[package\]\]|\Z)", text, re.M | re.S):
            try:
                record = tomllib.loads(match.group())["package"][0]
            except (ValueError, KeyError, IndexError):
                continue
            if record.get("name") == package and record.get("version") == version:
                version_line = re.search(r"^version\s*=.*$", match.group(), re.M)
                offset = match.start() + (version_line.start() if version_line else 0)
                break
    line = text.count("\n", 0, offset) + 1
    return dict(path=path, line=line, text=text.splitlines()[line - 1].strip()[:300], value=version)


def under(path, folder):
    return folder == "." or path == folder or path.startswith(folder + "/")


def nearest_config(path, configs, names):
    folder = PurePosixPath(path).parent
    while True:
        for name in names:
            candidate = str(folder / name)
            if candidate in configs:
                return candidate
        if str(folder) == ".":
            return None
        folder = folder.parent


def detect(entries, configs, js_references):
    # Vendor manifests describe the vendored package, not this project's toolchain.
    configs = {
        p: text
        for p, text in configs.items()
        if not any(
            part in ("vendor", "third_party", "third-party") for part in PurePosixPath(p).parts
        )
    }
    technologies, notes, decoded = {}, [], {}
    for path, text in configs.items():
        if PurePosixPath(path).name not in (
            "package.json",
            "package-lock.json",
            "npm-shrinkwrap.json",
            "pyproject.toml",
            "uv.lock",
        ):
            continue
        try:
            decoded[path] = (
                tomllib.loads(text) if path.endswith((".toml", ".lock")) else json.loads(text)
            )
            if not isinstance(decoded[path], dict):
                raise ValueError("配置必须是对象")
        except (ValueError, TypeError) as exc:
            notes.append(
                dict(kind="technology", path=path, message=f"技术栈配置无效：{type(exc).__name__}")
            )

    def technology(key, label=None, category=None):
        if key not in technologies:
            name, cat, _ = REGISTRY.get(key, (label, category, []))
            technologies[key] = dict(
                id=key,
                name=name,
                category=cat,
                declarations=[],
                locked=[],
                references=[],
                languageEvidence=[],
            )
        return technologies[key]

    def declare(key, path, text, needle, value, selector):
        item = technology(key)
        item["declarations"].append(evidence(path, text, needle, "declared", value, selector))
        return item

    for item in entries:
        if item["category"] in ("config", "third-party") or item["captureStatus"] != "captured":
            continue
        language = item["language"]
        label = {
            "typescript": "TypeScript",
            "javascript": "JavaScript",
            "python": "Python",
            "go": "Go",
            "rust": "Rust",
            "css": "CSS",
            "html": "HTML",
            "sql": "SQL",
            "cpp": "C++",
            "c": "C",
            "csharp": "C#",
        }.get(language, language)
        tech = technology(
            "node:typescript" if language == "typescript" else f"language:{language}",
            label,
            "language",
        )
        tech["languageEvidence"].append(
            dict(path=item["id"], kind="language", text=f"源码语言：{language}")
        )
    for path, doc in decoded.items():
        name, text = PurePosixPath(path).name, configs[path]
        if name == "package.json":
            for field in (
                "dependencies",
                "devDependencies",
                "optionalDependencies",
                "peerDependencies",
            ):
                values = doc.get(field, {})
                if not isinstance(values, dict):
                    notes.append(
                        dict(kind="technology", path=path, message=f"{field} 不是依赖对象")
                    )
                    continue
                for package, constraint in values.items():
                    key = "node:" + package
                    if key not in REGISTRY or not isinstance(constraint, str):
                        continue
                    item = declare(
                        key, path, text, json.dumps(package), constraint, f"{field}.{package}"
                    )
                    lock_path = nearest_config(
                        path, configs, ["npm-shrinkwrap.json", "package-lock.json"]
                    )
                    if lock_path:
                        lock = decoded.get(lock_path, {})
                        packages = lock.get("packages", {})
                        if not isinstance(packages, dict):
                            continue
                        scope = str(
                            PurePosixPath(path).parent.relative_to(PurePosixPath(lock_path).parent)
                        )
                        while True:
                            location = str(PurePosixPath(scope) / "node_modules" / package)
                            record = packages.get(location)
                            if isinstance(record, dict) and isinstance(record.get("version"), str):
                                # A selector identifies the exact record even in compact JSON.
                                item["locked"].append(
                                    {
                                        **locked_evidence(
                                            lock_path,
                                            configs[lock_path],
                                            package,
                                            record["version"],
                                            location,
                                        ),
                                        "kind": "locked",
                                        "selector": f"packages[{location}].version",
                                        "scope": str(PurePosixPath(path).parent),
                                    }
                                )
                                break
                            if scope == ".":
                                break
                            scope = str(PurePosixPath(scope).parent)
                        if (
                            isinstance(lock.get("lockfileVersion", 0), int)
                            and lock.get("lockfileVersion", 0) < 2
                        ):
                            notes.append(
                                dict(
                                    kind="technology",
                                    path=lock_path,
                                    message="npm v1 锁文件暂不解析精确版本",
                                )
                            )
            engines = doc.get("engines", {})
            if isinstance(engines, dict) and isinstance(engines.get("node"), str):
                technology("runtime:node", "Node.js", "runtime")["declarations"].append(
                    evidence(path, text, '"node"', "declared", engines["node"], "engines.node")
                )
        elif name == "pyproject.toml":
            project = doc.get("project", {})
            if not isinstance(project, dict):
                notes.append(dict(kind="technology", path=path, message="project 不是配置对象"))
                continue
            if isinstance(project.get("requires-python"), str):
                technology("language:python", "Python", "language")["declarations"].append(
                    evidence(
                        path,
                        text,
                        "requires-python",
                        "declared",
                        project["requires-python"],
                        "project.requires-python",
                    )
                )
            values = (
                list(project.get("dependencies", []))
                if isinstance(project.get("dependencies", []), list)
                else []
            )
            optional = project.get("optional-dependencies", {})
            groups = doc.get("dependency-groups", {})
            for collection in (optional, groups):
                if isinstance(collection, dict):
                    for group in collection.values():
                        if isinstance(group, list):
                            values.extend(group)
            for value in values:
                if isinstance(value, str):
                    python_requirement(value, path, text, decoded, configs, declare)
    for path, text in configs.items():
        if PurePosixPath(path).name == "requirements.txt":
            for value in text.splitlines():
                if value.strip() and not value.lstrip().startswith(("#", "-")):
                    python_requirement(value.strip(), path, text, decoded, configs, declare)
        elif PurePosixPath(path).name in (".nvmrc", ".node-version", ".python-version"):
            key, label, cat = (
                ("language:python", "Python", "language")
                if path.endswith(".python-version")
                else ("runtime:node", "Node.js", "runtime")
            )
            if text.strip():
                technology(key, label, cat)["declarations"].append(
                    evidence(path, text, text.splitlines()[0], "declared", text.strip()[:80])
                )
    references = list(js_references)
    project_sources = {x["id"] for x in entries if x["category"] != "third-party"}
    for ref in references:
        if ref["path"] not in project_sources:
            continue
        ecosystem = ref.get("ecosystem", "node")
        for key, (_, _, modules) in REGISTRY.items():
            if not key.startswith(ecosystem + ":"):
                continue
            if any(
                ref["specifier"] == m
                or ref["specifier"].startswith(m + ("/" if ecosystem == "node" else "."))
                for m in modules
            ):
                technology(key)["references"].append(dict(**ref, kind="reference"))
    for item in technologies.values():
        for field in ("declarations", "locked", "references", "languageEvidence"):
            item[field] = list({json.dumps(x, sort_keys=True): x for x in item[field]}.values())
        item["runtimeStatus"] = "not-observed"
    order = {"language": 0, "runtime": 1, "framework": 2, "build": 3, "storage": 4, "test": 5}
    return sorted(
        technologies.values(), key=lambda t: (order[t["category"]], t["name"].lower())
    ), notes


def python_requirement(value, path, text, decoded, configs, declare):
    match = re.match(r"^([\w.-]+)(?:\[[^\]]+\])?(.*)$", value)
    if not match:
        return
    package, constraint = match.groups()
    package = re.sub(r"[-_.]+", "-", package).lower()
    key = "python:" + package
    if key not in REGISTRY:
        return
    item = declare(key, path, text, value, constraint.strip() or "未限定版本", "dependencies")
    lock_path = nearest_config(path, configs, ["uv.lock"])
    if not lock_path:
        return
    records = decoded.get(lock_path, {}).get("package", [])
    if not isinstance(records, list):
        return
    for record in records:
        if (
            isinstance(record, dict)
            and record.get("name") == package
            and isinstance(record.get("version"), str)
        ):
            item["locked"].append(
                {
                    **locked_evidence(lock_path, configs[lock_path], package, record["version"]),
                    "kind": "locked-candidate",
                    "selector": f"package[name={package},version={record['version']}]",
                    "scope": str(PurePosixPath(path).parent),
                    "note": "uv 锁文件候选版本；未求值环境标记",
                }
            )
