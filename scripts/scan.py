"""Read-only, bounded Python / JS / TS source collector. Never imports project code."""

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from counting import aggregate, count_files, summarize
from inventory import RULES, capture, git, verify_inputs
from mapping import group_sources, project_edges
from node_runtime import resolve_node
from technologies import REGISTRY, RULE_VERSION, detect


def python_references(files):
    py = [f for f in files if f["language"] == "python"]
    index, namespaces = {}, set()
    for f in py:
        parts = Path(f["id"]).with_suffix("").parts
        module = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        variants = {module}
        for marker in ("src", "backend"):
            if marker in parts:
                tail = parts[parts.index(marker) + 1 :]
                variants.add(".".join(tail[:-1] if tail and tail[-1] == "__init__" else tail))
        for key in variants:
            if key:
                index.setdefault(key, f["id"])
                namespaces.add(key.split(".")[0])
    imports, unresolved, external, external_refs = [], [], 0, []
    for f in py:
        try:
            tree = ast.parse(f["content"], filename=f["id"])
        except SyntaxError as exc:
            unresolved.append(dict(kind="syntax", path=f["id"], line=exc.lineno, message=exc.msg))
            continue
        f["symbols"] = [
            dict(name=n.name, line=n.lineno, kind=type(n).__name__)
            for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]
        for node in ast.walk(tree):
            candidates = []
            if isinstance(node, ast.Import):
                candidates = [(n.name, False) for n in node.names]
            elif isinstance(node, ast.ImportFrom):
                package = list(Path(f["id"]).parent.parts)
                if node.level:
                    if node.level > len(package):
                        unresolved.append(
                            dict(
                                kind="unresolved",
                                path=f["id"],
                                line=node.lineno,
                                message="相对导入超出包范围",
                            )
                        )
                        continue
                    prefix = ".".join(package[: len(package) - node.level + 1])
                    base = ".".join(x for x in (prefix, node.module) if x)
                else:
                    base = node.module or ""
                candidates = [
                    (f"{base}.{alias.name}" if base else alias.name, bool(node.level))
                    if f"{base}.{alias.name}" in index
                    else (base, bool(node.level))
                    for alias in node.names
                ]
            elif isinstance(node, ast.Call) and (
                (isinstance(node.func, ast.Name) and node.func.id == "__import__")
                or (isinstance(node.func, ast.Attribute) and node.func.attr == "import_module")
            ):
                unresolved.append(
                    dict(
                        kind="dynamic", path=f["id"], line=node.lineno, message="动态导入未静态展开"
                    )
                )
            for module, relative in candidates:
                if module in index:
                    target = index[module]
                    if target != f["id"]:
                        imports.append(
                            dict(
                                **{"from": f["id"], "to": target},
                                line=node.lineno,
                                specifier=module,
                                kind="import",
                                text=ast.get_source_segment(f["content"], node) or "",
                            )
                        )
                elif relative or module.split(".")[0] in namespaces:
                    unresolved.append(
                        dict(
                            kind="unresolved",
                            path=f["id"],
                            line=node.lineno,
                            message=f"未解析项目导入：{module}",
                        )
                    )
                else:
                    external += 1
                    external_refs.append(
                        dict(
                            path=f["id"],
                            line=node.lineno,
                            specifier=module,
                            ecosystem="python",
                            text=ast.get_source_segment(f["content"], node) or "",
                        )
                    )
    unique = {(r["from"], r["to"], r["line"]): r for r in imports}
    return list(unique.values()), unresolved, external, external_refs


def scan_project(project, mapping_path=None, node=None, scc=None, work_dir=None, *, snapshot_context=None):
    root = Path(project).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("项目路径必须是目录")
    with tempfile.TemporaryDirectory(
        prefix="code-architecture-", dir=work_dir or os.environ.get("CODE_ARCHITECTURE_TEST_TMP")
    ) as temporary:
        entries, configs, originals, notes = capture(root, Path(temporary))
        inventory_sources = [x for x in entries if x["category"] != "config"]
        if not inventory_sources:
            raise ValueError("没有发现可盘点的源码文件")
        files = [x for x in inventory_sources if x.get("content") is not None]
        imports, diagnostics, external, python_external_refs = python_references(files)
        syntax = {d["path"] for d in diagnostics if d["kind"] == "syntax"}
        for f in files:
            if f["language"] == "python":
                f["parseStatus"] = "failed" if f["id"] in syntax else "parsed"
                if f["id"] in syntax:
                    f["parseReason"] = next(d["message"] for d in diagnostics if d.get("path") == f["id"] and d["kind"] == "syntax")
        js_files = [f for f in files if f["language"] != "python"]
        external_refs = []
        runtime = None
        if js_files:
            runtime = resolve_node(node)
            parser = Path(__file__).with_name("parse-js.cjs")
            try:
                if runtime["status"] != "ready":
                    raise ValueError(runtime["message"])
                if not parser.exists():
                    raise ValueError("缺少打包的 JS/TS 解析器 scripts/parse-js.cjs")
                result = subprocess.run(
                    [runtime["executable"], str(parser)],
                    input=json.dumps(dict(files=js_files, configs=configs)),
                    text=True,
                    capture_output=True,
                    timeout=60,
                    check=True,
                )
                parsed = json.loads(result.stdout)
                imports.extend(parsed["imports"])
                diagnostics.extend(parsed["diagnostics"])
                external += parsed["external"]
                external_refs = parsed.get("externalReferences", [])
                syntax = {d["path"] for d in parsed["diagnostics"] if d["kind"] == "syntax"}
                for f in js_files:
                    f["parseStatus"] = "failed" if f["id"] in syntax else "parsed"
                    if f["id"] in syntax:
                        f["parseReason"] = next(d["message"] for d in parsed["diagnostics"] if d.get("path") == f["id"] and d["kind"] == "syntax")
                    f["symbols"] = parsed.get("symbols", {}).get(f["id"], [])
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                if isinstance(exc, subprocess.TimeoutExpired):
                    reason = "JS/TS 解析执行超过 60 秒，引用未解析"
                elif isinstance(exc, subprocess.CalledProcessError):
                    reason = f"JS/TS 解析器执行失败（退出码 {exc.returncode}）"
                elif isinstance(exc, ValueError):
                    reason = str(exc)
                else:
                    reason = "无法启动 JS/TS 解析器；请检查 Node 可执行文件及访问权限"
                diagnostics.append(
                    dict(kind="parser", message=reason + "；代码盘点与计数仍保留")
                )
                for f in js_files:
                    f.update(parseStatus="unavailable", parseReason=reason)
        tool = count_files(Path(temporary), entries, scc)
        changed = verify_inputs(root, entries, originals)
        for path in changed:
            configs.pop(path, None)
            diagnostics.append(
                dict(kind="changed", path=path, message="扫描期间文件变化，相关结论已移除，待重扫")
            )
        available = {
            x["id"]
            for x in files
            if x["captureStatus"] == "captured" and x["parseStatus"] == "parsed"
        }
        imports = list(
            {
                (r["from"], r["to"], r["line"]): r
                for r in imports
                if r["from"] in available and r["to"] in available
            }.values()
        )
        external_refs = [r for r in external_refs + python_external_refs if r["path"] in available]
        external = len(external_refs)
        technologies, tech_notes = detect(entries, configs, external_refs)
        files = [
            {k: v for k, v in f.items() if k not in ("metrics",)}
            for f in files
            if f["captureStatus"] == "captured"
        ]
        inventory = [
            {k: v for k, v in x.items() if k not in ("content", "symbols")} for x in entries
        ]
    if tool["status"] != "ready":
        notes.append(dict(kind="counter", message=tool["message"]))
    mapping = json.loads(Path(mapping_path).read_text()) if mapping_path else None
    groups, mapping_notes = group_sources(inventory_sources, mapping)
    for group in groups:
        member_ids = set(group["files"])
        members = [x for x in inventory_sources if x["id"] in member_ids]
        group["stats"] = dict(
            total=aggregate(members, tool),
            own=aggregate([x for x in members if x["category"] == "source"], tool),
            incoming=sum(r["to"] in member_ids and r["from"] not in member_ids for r in imports),
            outgoing=sum(r["from"] in member_ids and r["to"] not in member_ids for r in imports),
        )
    source_digest = hashlib.sha256()
    for f in files:
        source_digest.update(f["id"].encode() + b"\0" + f["hash"].encode())
    for name, content in sorted(configs.items()):
        source_digest.update(name.encode() + b"\0" + content.encode())
    source_hash = source_digest.hexdigest()
    mapping_hash = hashlib.sha256(
        json.dumps(
            [{k: v for k, v in g.items() if k != "stats"} for g in groups],
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    analysis_hash = hashlib.sha256(
        json.dumps(
            dict(
                inputs=[{k: x.get(k) for k in ("id", "hash", "captureStatus")} for x in inventory],
                classification=RULES,
                technologyRegistry=REGISTRY,
                technologyRuleVersion=RULE_VERSION,
                counter=tool,
                parserVersion=3,
                nodeRuntime=runtime,
            ),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    head = (
        None if git(root, "check-ignore", "--quiet", ".") == b"" else git(root, "rev-parse", "HEAD")
    )
    parse_counts = {
        state: sum(x["parseStatus"] == state for x in inventory_sources)
        for state in ("parsed", "failed", "unsupported", "skipped", "unavailable", "changed")
    }
    # Retain captured inputs privately for optional semantic queries. The public
    # scan JSON and its import/architecture edge semantics stay unchanged.
    if snapshot_context is not None:
        snapshot_context.update(files=files, configs=dict(configs), imports=imports,
                                runtime=runtime, snapshotId=analysis_hash[:12])
    return dict(
        version=1,
        project=dict(name=root.name, root=str(root), sample=False),
        snapshot=dict(
            id=analysis_hash[:12],
            sourceHash=source_hash,
            analysisInputHash=analysis_hash,
            mappingHash=mapping_hash,
            commit=head.decode().strip() if head else None,
            scannedAt=datetime.now(timezone.utc).isoformat(),
        ),
        files=files,
        inventory=inventory,
        technologies=technologies,
        metrics=summarize(inventory, tool),
        coverage=dict(
            counting=dict(
                total=len(inventory_sources),
                counted=sum(x["countStatus"] == "counted" for x in inventory_sources),
            ),
            parsing=dict(total=len(inventory_sources), **parse_counts),
            parsingTool=runtime,
            classificationRules=RULES,
            inventoryLimits=dict(
                files=50000, fileBytes=16 * 1024 * 1024, totalBytes=256 * 1024 * 1024
            ),
            parserLimits=dict(files=5000, fileBytes=512 * 1024, totalBytes=32 * 1024 * 1024),
        ),
        groups=groups,
        imports=imports,
        edges=project_edges(groups, imports),
        diagnostics=notes + diagnostics + tech_notes + mapping_notes,
        externalImports=external,
        mappingPath=str(Path(mapping_path).resolve()) if mapping_path else None,
        limitations=[
            "仅解析静态导入关系，不声称是运行时调用图。",
            "技术识别支持 Node/npm 与 Python/uv；不观察安装环境或运行状态。",
            "自有源码按路径和生成标记分类，不代表版权或作者判定。",
            "盘点语言由扩展名规则识别；未知扩展名、二进制及非 UTF-8 文件不参与源码统计。",
            (
                "Git 排除规则与依赖、构建、运行数据目录始终排除；"
                "测试、生成和已跟踪第三方源码单独计数。"
            ),
        ],
    )


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("project")
    cli.add_argument("--mapping")
    cli.add_argument("--node")
    cli.add_argument("--scc", help="scc 可执行文件路径；省略时检测打包工具或 PATH")
    cli.add_argument("--work-dir", help="捕获文件的短生命周期工作目录；不写入目标源码")
    cli.add_argument("--output", required=True, help="显式指定 JSON 输出；不会写入被扫描项目")
    args = cli.parse_args()
    try:
        data = scan_project(args.project, args.mapping, args.node, args.scc, args.work_dir)
        output = Path(args.output).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        print(
            json.dumps(
                dict(
                    output=str(output),
                    files=len(data["files"]),
                    references=len(data["imports"]),
                    diagnostics=len(data["diagnostics"]),
                ),
                ensure_ascii=False,
            )
        )
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
