"""Validated source membership and evidence-backed graph projection."""

from collections import defaultdict
from pathlib import PurePosixPath


def group_sources(files, mapping=None):
    known = {f["id"] for f in files}
    diagnostics = []
    if mapping is None:
        buckets = defaultdict(list)
        for file in files:
            parts = PurePosixPath(file["id"]).parts
            prefix = (
                "/".join(parts[:2]) if len(parts) > 2 else parts[0] if len(parts) > 1 else "根目录"
            )
            buckets[prefix].append(file["id"])
        groups = [
            dict(
                id=f"directory:{p}",
                title=p,
                files=items,
                origin="directory",
                description="根据源码目录生成，尚未整理为系统架构。",
            )
            for p, items in sorted(buckets.items())
        ]
    else:
        if (
            not isinstance(mapping, dict)
            or mapping.get("version") != 1
            or not isinstance(mapping.get("groups"), list)
        ):
            raise ValueError("架构映射必须包含 version: 1 与 groups 数组")
        groups, ids = [], set()
        for item in mapping["groups"]:
            if not isinstance(item, dict):
                raise ValueError("架构分组必须是对象")
            gid, title, members = item.get("id"), item.get("title"), item.get("files")
            if (
                not isinstance(gid, str)
                or not gid
                or gid in ids
                or not isinstance(title, str)
                or not title.strip()
            ):
                raise ValueError("架构 ID 必须唯一，名称不能为空")
            if not isinstance(members, list) or not all(isinstance(x, str) for x in members):
                raise ValueError("files 必须是相对路径数组")
            origin = item.get("origin", "inferred")
            if origin not in ("confirmed", "inferred", "directory"):
                raise ValueError("origin 仅支持 confirmed、inferred、directory")
            ids.add(gid)
            missing = sorted(set(members) - known)
            if missing:
                diagnostics.append(
                    dict(
                        kind="mapping",
                        message=f"{title} 有 {len(missing)} 个源码成员不存在或未被扫描",
                        paths=missing,
                    )
                )
            groups.append(
                dict(
                    id=gid,
                    title=title.strip(),
                    files=sorted(set(members) & known),
                    origin=origin,
                    description=str(item.get("description", "")),
                    source=str(item.get("source", "架构映射文件")),
                )
            )
    return groups, diagnostics


def project_edges(groups, imports):
    owners = defaultdict(list)
    for group in groups:
        for path in group["files"]:
            owners[path].append(group["id"])
    pairs = defaultdict(list)
    for ref in imports:
        for source in owners[ref["from"]]:
            # A shared member is still internal when it belongs to this source
            # group. Its other memberships do not imply a new cross-group edge.
            if source in owners[ref["to"]]:
                continue
            for target in owners[ref["to"]]:
                if source != target:
                    pairs[(source, target)].append(ref)
    return [
        dict(id=f"{a}=>{b}", source=a, target=b, evidence=refs)
        for (a, b), refs in sorted(pairs.items())
    ]
