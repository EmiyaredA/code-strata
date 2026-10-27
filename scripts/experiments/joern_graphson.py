"""Read Joern GraphSON exports without relying on a graph database client."""

import json


def unwrap(value):
    if isinstance(value, dict):
        if "@value" in value:
            if value.get("@type") == "g:Map":
                items = value["@value"]
                return {str(unwrap(items[i])): unwrap(items[i+1]) for i in range(0,len(items),2)}
            return unwrap(value["@value"])
        return {k: unwrap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [unwrap(x) for x in value]
    return value


def properties(value):
    result = {}
    for key, entries in value.items():
        if isinstance(entries, list):
            entries = entries[0] if entries else None
        if isinstance(entries, dict) and "value" in entries:
            entries = entries["value"]
        result[key] = entries
    return result


def read_graphson(path):
    if path.suffix == '.jsonl':
        nodes,edges,metadata=[],[],{}
        with path.open() as stream:
            for line in stream:
                row=json.loads(line)
                kind=row.pop('recordType')
                if kind=='node': nodes.append(row)
                elif kind=='edge': edges.append(row)
                else: metadata=row
        return dict(nodes=nodes,edges=edges,metadata=metadata)
    with path.open() as stream:
        first = stream.readline()
        try:
            first_record = json.loads(first)
        except json.JSONDecodeError:
            stream.seek(0)
            records = [json.load(stream)]
        else:
            records = [first_record]
            records.extend(json.loads(line) for line in stream if line.strip())
    vertices, edges = [], []
    for record in records:
        record = unwrap(record)
        if "vertices" in record:
            vertices.extend(record["vertices"])
            edges.extend(record.get("edges", []))
        elif "nodes" in record:
            vertices.extend(record["nodes"])
            edges.extend(record.get("edges", []))
        else:
            vertices.append(record)
    nodes = []
    keys = {"NAME": "name", "CODE": "code", "FULL_NAME": "fullName", "TYPE_FULL_NAME": "type",
            "FILENAME": "filename", "LINE_NUMBER": "line", "COLUMN_NUMBER": "column",
            "LINE_NUMBER_END": "endLine", "COLUMN_NUMBER_END": "endColumn", "ORDER": "order",
            "IS_EXTERNAL": "external", "DISPATCH_TYPE": "dispatchType", "ARGUMENT_INDEX": "argumentIndex",
            "CONTROL_STRUCTURE_TYPE": "controlType", "METHOD_FULL_NAME": "methodFullName",
            "IMPORTED_ENTITY":"importedEntity", "IMPORTED_AS":"importedAs"}
    for vertex in vertices:
        prop = properties(vertex.get("properties", {}))
        nodes.append(dict(id=str(vertex["id"]), label=vertex["label"], **{dest: prop.get(key) for key,dest in keys.items()}))
        for label, outgoing in vertex.get("outE", {}).items():
            for edge in outgoing:
                edges.append(dict(label=label, source=str(vertex["id"]), target=str(edge["inV"])))
    normalized_edges = []
    for edge in edges:
        prop=properties(edge.get('properties',{}))
        normalized_edges.append(dict(label=edge["label"], source=str(edge.get("source", edge.get("outV"))),
                                     target=str(edge.get("target", edge.get("inV"))),
                                     variable=prop.get('EdgeProperty')))
    return dict(nodes=nodes, edges=normalized_edges)
