"""Source-backed semantic model; no AST/compiler objects cross the boundary."""
import hashlib

VERSION = 1
FUNCTIONS = {"function", "method", "constructor", "lambda"}
VARIABLES = {"variable", "parameter"}


def identity(path, kind, start, end):
    raw = f"{path}\0{kind}\0{start[0]}:{start[1]}\0{end[0]}:{end[1]}"
    return kind + ":" + hashlib.sha256(raw.encode()).hexdigest()[:20]


def edge(kind, source, target, **extra):
    key = f"{kind}\0{source}\0{target}\0{extra.get('siteId', '')}"
    return dict(id=hashlib.sha256(key.encode()).hexdigest()[:20], kind=kind,
                source=source, target=target, **extra)


def empty():
    return dict(version=VERSION, nodes=[], relations=[], diagnostics=[])


def merge(parts):
    result = empty()
    for part in parts:
        for key in ("nodes", "relations", "diagnostics"):
            result[key].extend(part.get(key, []))
    result["nodes"] = list({n["id"]: n for n in result["nodes"]}.values())
    result["relations"] = list({r["id"]: r for r in result["relations"]}.values())
    return result
