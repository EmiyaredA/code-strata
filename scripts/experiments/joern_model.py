"""Normalize experimental Joern records; never infer relationships from name matches."""

from collections import Counter, defaultdict, deque
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import time

KINDS = {
    "FILE": "file", "TYPE_DECL": "class", "METHOD": "function",
    "METHOD_PARAMETER_IN": "parameter", "LOCAL": "variable", "MEMBER": "variable",
    "CALL": "callsite", "IDENTIFIER": "identifier", "FIELD_IDENTIFIER": "identifier",
    "CONTROL_STRUCTURE": "statement", "RETURN": "statement", "BLOCK": "statement",
    "LITERAL": "statement", "METHOD_REF": "identifier", "METHOD_RETURN": "statement",
    "UNKNOWN": "statement", "JUMP_TARGET": "statement",
    "IMPORT": "import",
}
RELATIONS = {"AST": "contains", "CALL": "calls", "REF": "references", "CFG": "controlFlow", "REACHING_DEF": "dataDependency", "IMPORTS":"imports"}


def source_column(line, token, raw):
    """Return a zero-based source column only when source text corroborates it."""
    if not isinstance(raw, int) or not token:
        return None, "unverified"
    head = token.splitlines()[0]
    candidates = []
    for column in (raw, raw-1):
        if column < 0:
            continue
        candidates.append((column,"characters"))
        for encoding, units in (("utf-8",1),("utf-16-le",2)):
            try:
                prefix = line.encode(encoding)[:column*units].decode(encoding)
                candidates.append((len(prefix),encoding))
            except UnicodeError:
                pass
    matches = {(column,encoding) for column,encoding in candidates if line[column:].startswith(head)}
    positions = {column for column,_ in matches}
    if len(positions) == 1:
        return positions.pop(), "source-text-matched"
    return None, "unverified"


def _path(value, root, sources):
    value = str(value or "").replace("\\", "/")
    prefix = str(root).replace("\\", "/").rstrip("/") + "/"
    if value.startswith(prefix):
        value = value[len(prefix):]
    value = value.removeprefix("./")
    return value if value in sources else None


def normalize(raw, sources, snapshot, language, root):
    """Input: explicit nodes/edges with source properties; internal ids stay in raw evidence."""
    by_raw = {str(n["id"]): n for n in raw["nodes"]}
    children, parents = defaultdict(list), {}
    for edge in raw["edges"]:
        if edge["label"] == "AST":
            source, target = str(edge["source"]), str(edge["target"])
            children[source].append(target)
            parents.setdefault(target, source)
    locations, owners, ast_paths = {}, {}, {}
    seeds = []
    for rid, node in by_raw.items():
        path = _path(node.get("filename") or (node.get("name") if node["label"] == "FILE" else None), root, sources)
        if path:
            locations[rid] = path
            if node.get('owner') is not None:
                owners[rid] = str(node['owner'])
            if node["label"] == "METHOD":
                owners[rid] = rid
            ast_paths[rid] = str(node.get("fullName") or node.get("name") or path)
            seeds.append(rid)
    queue = deque(seeds)
    seen = set()
    while queue:
        rid = queue.popleft()
        if rid in seen:
            continue
        seen.add(rid)
        for child in children[rid]:
            node = by_raw.get(child, {})
            if child not in locations and rid in locations:
                locations[child] = locations[rid]
            if node.get("label") == "METHOD":
                owners[child] = child
            elif rid in owners:
                owners[child] = owners[rid]
            ast_paths.setdefault(child, ast_paths.get(rid, "") + "/" + str(node.get("order", "")) + ":" + node.get("label", ""))
            queue.append(child)
    objects, id_map, collisions = [], {}, Counter()
    for rid, node in by_raw.items():
        label, path = node["label"], locations.get(rid)
        if label not in KINDS or not path:
            continue
        name = node.get("name") or ""
        code = node.get("code") or ""
        synthetic = label != "FILE" and (not node.get("line") or name in ("<global>", "<program>", "<module>", ":program"))
        constructor = label == "CALL" and name == "<operator>.new"
        operator = label == "CALL" and not constructor and (name.startswith("<operator>") or name.startswith("<operators>"))
        if label == "METHOD" and node.get("external"):
            continue
        kind = "statement" if operator else KINDS[label]
        identity = [snapshot, language, kind, path, node.get("line"), node.get("column"), node.get("fullName"), name, ast_paths.get(rid), code,node.get('type'),node.get('argumentIndex'),node.get('order')]
        oid = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:24]
        collisions[oid] += 1
        # Identical source identities are canonicalized; retain all raw-id aliases
        # for relation conversion instead of silently dropping their edges.
        id_map[rid] = oid
        if collisions[oid] > 1:
            continue
        line = node.get("line")
        lines = sources[path].splitlines()
        line_valid = isinstance(line, int) and 1 <= line <= len(lines)
        source_line = lines[line-1] if line_valid else ''
        source_backed = False
        if line_valid:
            if label == 'CALL':
                compact = re.sub(r'\s+','',code)
                nearby = re.sub(r'\s+','', '\n'.join(lines[line-1:min(len(lines),line+3)]))
                source_backed = bool(compact and compact in nearby) or bool(name and re.search(re.escape(name)+r'\s*\(',source_line))
                if not operator and not source_backed:
                    synthetic = True
            elif label in ('LOCAL','MEMBER','METHOD_PARAMETER_IN'):
                source_backed = bool(name and re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',source_line))
                if not source_backed:
                    synthetic = True
            else:
                source_backed = bool(name and name in source_line)
        if label == 'METHOD' and (name.startswith('<') or name == ':program'):
            synthetic = True
        if label == 'TYPE_DECL':
            actual_class = bool(re.search(r'\bclass\s+'+re.escape(name)+r'(?!\w)',source_line))
            kind = 'class' if actual_class else 'type'
        column, column_status = source_column(lines[line-1], code or name, node.get("column")) if line_valid else (None,"unverified")
        obj = dict(id=oid, kind=kind, label=label, path=path, name=name, code=code,
                   fullName=node.get("fullName"), type=node.get("type"),
                   location=dict(line=line if line_valid else None, column=column, rawColumn=node.get("column"),
                                 endLine=node.get("endLine"), endColumn=node.get("endColumn"),
                                 status="line-in-range" if line_valid else "unlocated",
                                 columnStatus=column_status, endColumnStatus="raw-unverified"),
                   synthetic=synthetic, operator=operator, dispatchType=node.get("dispatchType"),
                   constructorCall=constructor,
                   sourceBacked=source_backed,
                   detail=node.get('detail',True),codeTruncated=node.get('codeTruncated',False),
                   argumentIndex=node.get("argumentIndex"), controlType=node.get("controlType"),
                   importedEntity=node.get("importedEntity"), importedAs=node.get("importedAs"))
        objects.append(obj)
    index = {x["id"]: x for x in objects}
    for rid, oid in id_map.items():
        index[oid]["owner"] = id_map.get(owners.get(rid))
    relations, seen_edges = [], set()
    unresolved = []
    targets = defaultdict(list)
    for edge in raw["edges"]:
        if edge["label"] == "CALL":
            targets[str(edge["source"])].append(str(edge["target"]))
        source, target = id_map.get(str(edge["source"])), id_map.get(str(edge["target"]))
        kind = RELATIONS.get(edge["label"])
        if not source or not target or not kind or (kind, source, target) in seen_edges:
            continue
        seen_edges.add((kind, source, target))
        status = "candidate" if kind in ("calls", "dataDependency") else "extracted"
        relations.append(dict(kind=kind, source=source, target=target, status=status,variable=edge.get('variable'),
                              evidence=dict(path=index[source]["path"], **index[source]["location"])))
    for rid, oid in id_map.items():
        obj = index[oid]
        if obj["kind"] != "callsite" or obj["synthetic"]:
            continue
        internal = [id_map[t] for t in targets[rid] if t in id_map and index[id_map[t]]["kind"] == "function"]
        obj["resolution"] = "candidate" if internal else "unresolved"
        if not internal:
            unresolved.append(dict(id=oid, path=obj["path"], line=obj["location"]["line"], code=obj["code"],
                                   reason="No internal implementation target exported by Joern; external/dynamic/missing targets are not guessed."))
    files = sorted({x["path"] for x in objects})
    return dict(version=1, engine=dict(name="joern", version="4.0.666"), language=language,
                normalizerHash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                exportScope=raw.get('metadata',{'scope':'full GraphSON'}),
                snapshot=snapshot, objects=objects, relations=relations, unresolved=unresolved,
                coverage=dict(inputFiles=len(sources), representedFiles=len(files),
                              missingFiles=sorted(set(sources) - set(files)),
                              objects=dict(Counter(x["kind"] for x in objects)),
                              relations=dict(Counter(x["kind"] for x in relations)),
                              identityCollisions=sum(n-1 for n in collisions.values())),
                limitations=["Static targets remain candidates; no runtime observations.",
                             "Variable references are separate from reaching-definition/data-dependency edges.",
                             "Columns are zero-based only when matched to source; raw/end coordinates remain explicitly labeled.",
                             "Control-flow graph completeness is evaluated per language/construct, not assumed."])


class QueryIndex:
    """Small consumer independent of Joern process/database ids."""
    def __init__(self, model):
        self.model = model
        self.objects = {x["id"]: x for x in model["objects"]}
        self.outgoing, self.incoming = defaultdict(list), defaultdict(list)
        for edge in model["relations"]:
            self.outgoing[edge["source"]].append(edge)
            self.incoming[edge["target"]].append(edge)

    def neighbors(self, oid, kinds):
        return [e for e in self.outgoing[oid] + self.incoming[oid] if e["kind"] in kinds]

    def function(self, oid):
        owned = {x["id"] for x in self.objects.values() if x.get("owner") == oid}
        calls = [e for x in owned for e in self.outgoing[x] if e["kind"] == "calls"]
        callers = [e for e in self.incoming[oid] if e["kind"] == "calls"]
        scope=self.model.get('exportScope',{})
        detail='not-exported' if not self.objects[oid].get('detail',True) else 'partial' if scope.get('truncated') or scope.get('coreEdgesTruncated') else 'available'
        return dict(function=oid, detailStatus=detail, objects=sorted(owned), calls=calls, callers=callers,
                    coverage='Static candidates within the exported scope; no edges is not proof of no calls.')

    def logic(self, oid):
        owned = {x["id"] for x in self.objects.values() if x.get("owner") == oid}
        return [e for x in owned for e in self.outgoing[x] if e["kind"] in ("controlFlow", "references", "dataDependency") and e["target"] in owned]

    def file_dependencies(self):
        pairs = Counter()
        for edge in self.model["relations"]:
            if edge["kind"] != "calls":
                continue
            a, b = self.objects[edge["source"]]["path"], self.objects[edge["target"]]["path"]
            if a != b:
                pairs[(a, b)] += 1
        return [dict(source=a, target=b, callsites=count, basis="static-call-candidates") for (a,b),count in sorted(pairs.items())]

    def benchmark(self):
        roots = [x["id"] for x in self.objects.values() if x["kind"] == "function" and not x["synthetic"] and x.get('detail',True)][:20]
        values, samples = [], []
        for oid in roots:
            start = time.perf_counter_ns()
            result = self.function(oid)
            logic = self.logic(oid)
            elapsed = (time.perf_counter_ns()-start) / 1e6
            values.append(elapsed)
            samples.append(dict(id=oid, milliseconds=elapsed, members=len(result["objects"]), logicEdges=len(logic)))
        values.sort()
        return dict(scope="normalized in-memory consumer, not Joern query latency", samples=samples,
                    p50Ms=statistics.median(values) if values else None,
                    p95Ms=values[max(0,math.ceil(len(values)*.95)-1)] if values else None,
                    fileDependencies=self.file_dependencies())
