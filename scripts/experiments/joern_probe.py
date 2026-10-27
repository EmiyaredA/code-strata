"""Isolated, repeatable Joern evaluation. Never imports or runs the analyzed project."""

import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inventory import capture, verify_inputs
from joern_graphson import read_graphson
from joern_model import normalize, QueryIndex
from joern_process import run_process, tool_environment
from joern_semantics import check_semantics
from joern_syntax import syntax_checks

VERSION = "4.0.666"
HERE = Path(__file__).resolve().parent


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def size(path):
    return sum(x.stat().st_size for x in Path(path).rglob("*") if x.is_file())


def prepare(project, output):
    project = Path(project).resolve(strict=True)
    captured = output / "snapshot"
    captured.mkdir(parents=True, exist_ok=False)
    entries, configs, originals, diagnostics = capture(project, captured)
    languages = {"javascript": {}, "python": {}}
    for entry in entries:
        if entry.get("content") is None or entry["parseStatus"] != "pending":
            continue
        language = "python" if entry["language"] == "python" else "javascript"
        languages[language][entry["id"]] = entry["content"]
    for language, sources in languages.items():
        destination = output / language / "input"
        destination.mkdir(parents=True, exist_ok=True)
        for name, content in sources.items():
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode("utf-8"))
        if language == "javascript":
            for name, content in configs.items():
                if name.endswith("package.json") or Path(name).name.startswith("tsconfig"):
                    path = destination / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content)
    fingerprint = hashlib.sha256()
    for entry in entries:
        fingerprint.update(json.dumps({k:entry.get(k) for k in ("id","hash","captureStatus","parseStatus")}, sort_keys=True).encode())
    snapshot = fingerprint.hexdigest()
    manifest = dict(project=str(project), snapshot=snapshot,
                    files=[{k:v for k,v in e.items() if k not in ("content","symbols")} for e in entries],
                    languages={k:dict(files=len(v), bytes=sum(len(s.encode()) for s in v.values())) for k,v in languages.items()},
                    diagnostics=diagnostics, excludes="Existing inventory rules and parser budgets; source code only, no installed dependencies.")
    manifest['syntaxChecks']=syntax_checks(languages,configs)
    write_json(output / "snapshot.json", manifest)
    return project, entries, originals, languages, manifest


def fixture_checks(model, sources, expected):
    objects = {x["id"]:x for x in model["objects"]}
    source = next((p for p in sources if p.endswith(expected["source"])), None)
    if not source:
        return dict(status="no-fixture-source")
    markers = {}
    for i,line in enumerate(sources[source].splitlines(),1):
        if "CASE " in line:
            markers[line.split("CASE ",1)[1].strip()] = i
    results = []
    for test in expected["calls"]:
        test_source=next((p for p in sources if p.endswith(test.get('source',expected['source']))),source)
        line=next(i for i,text in enumerate(sources[test_source].splitlines(),1) if 'CASE '+test['case'] in text)
        callsites = [x for x in objects.values() if x["path"] == test_source and x["kind"] == "callsite" and x["location"]["line"] == line]
        targets = [objects[e["target"]] for e in model["relations"] if e["kind"] == "calls" and e["source"] in {x["id"] for x in callsites}]
        allowed = test.get("allowNames",[test["target"]])
        matches = [t for t in targets if t["name"] in allowed and t["path"].endswith(test["file"])]
        wrong = [t for t in targets if t not in matches]
        results.append(dict(case=test["case"], path=test_source,line=line, expected=test, status="matched" if matches and not wrong else "wrong-target" if wrong else "missing-target",
                            callsites=[x["code"] for x in callsites], targets=[dict(name=t["name"], path=t["path"], line=t["location"]["line"]) for t in targets]))
    variables = []
    for name in expected["variables"]:
        declarations = [x for x in objects.values() if x["path"] == source and x["name"] == name and x["kind"] in ("parameter","variable")]
        variables.append(dict(name=name, declarations=len(declarations), referenceEdges=sum(e["kind"] == "references" and e["target"] in {x["id"] for x in declarations} for e in model["relations"])))
    unknown = []
    for marker in expected["unresolved"]:
        line = markers[marker]
        calls = [x for x in objects.values() if x["path"] == source and x["kind"] == "callsite" and x["location"]["line"] == line]
        unknown.append(dict(case=marker, line=line, resolutions=[x.get("resolution") for x in calls],
                            candidateTargets=[objects[e["target"]]["fullName"] for e in model["relations"] if e["kind"] == "calls" and e["source"] in {x["id"] for x in calls}]))
    return dict(status="evaluated", calls=results, callCounts=dict(Counter(r["status"] for r in results)), variables=variables, dynamicCases=unknown,
                logicMarkers={m:markers[m] for m in expected["logic"]},
                logicStatus="Requires edge-level inspection; node presence alone is not proof of correct CFG.")


def select_review(model, sources):
    objects = {x["id"]:x for x in model["objects"]}
    calls, variables = [], []
    edges = model["relations"]
    targets_by_call={}
    refs_by_variable={}
    for edge in edges:
        if edge['kind']=='calls':targets_by_call.setdefault(edge['source'],[]).append(edge)
        if edge['kind']=='references':refs_by_variable.setdefault(edge['target'],[]).append(edge)
    stores={}
    if model['language']=='python':
        for path,text in sources.items():
            try:
                stores[path]={(n.lineno,n.id) for n in ast.walk(ast.parse(text)) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store)}
            except SyntaxError:
                stores[path]=set()
    def source_binding(obj):
        if not re.fullmatch(r'[$\w]+',obj['name']):return False
        line=obj['location']['line']
        if model['language']=='python':return (line,obj['name']) in stores.get(obj['path'],set())
        if not line:return False
        text=sources[obj['path']].splitlines()[line-1]
        match=re.search(r'\b(?:const|let|var)\s+([^=;]+)',text)
        binding=re.split(r'\s+(?:of|in)\s+',match[1])[0] if match else ''
        return bool(re.search(r'(?<!\w)'+re.escape(obj['name'])+r'(?!\w)',binding))
    ordered = sorted(objects.values(),key=lambda x:(x["path"], x["location"]["line"] or 0,x["name"]))
    eligible=[x for x in ordered if not x['synthetic'] and '/fixtures/' not in x['path'] and '_vendor/' not in x['path']]
    call_objects=[x for x in eligible if x['kind']=='callsite']
    linked=[x for x in call_objects if targets_by_call.get(x['id'])]
    unlinked=[x for x in call_objects if not targets_by_call.get(x['id'])]
    chosen=linked[:10]+unlinked[:10]
    chosen_ids={x['id'] for x in chosen}
    chosen+=( [x for x in call_objects if x['id'] not in chosen_ids][:20-len(chosen)] )
    chosen_ids={x['id'] for x in chosen}
    variable_positions=set()
    for obj in ordered:
        if obj["synthetic"] or "/fixtures/" in obj["path"] or "_vendor/" in obj["path"]:
            continue
        if obj["kind"] == "callsite" and obj['id'] in chosen_ids:
            selected = targets_by_call.get(obj['id'],[])
            targets = [dict(path=objects[e["target"]]["path"], line=objects[e["target"]]["location"]["line"], name=objects[e["target"]]["name"], code=objects[e["target"]]["code"][:500]) for e in selected]
            calls.append(dict(id=obj["id"], path=obj["path"], line=obj["location"]["line"], code=obj["code"], targets=targets,
                              resolution=obj.get("resolution"), verdict="pending-source-review", sourceContext=context(sources,obj)))
        position=(obj['path'],obj['location']['line'],obj['name'])
        if obj["kind"] == "variable" and len(variables) < 10 and source_binding(obj) and position not in variable_positions:
            variable_positions.add(position)
            refs = [objects[e["source"]] for e in refs_by_variable.get(obj['id'],[])]
            variables.append(dict(id=obj["id"],path=obj["path"],line=obj["location"]["line"],name=obj["name"],
                                  references=[dict(path=r["path"],line=r["location"]["line"],code=r["code"]) for r in refs],
                                  verdict="pending-source-review",sourceContext=context(sources,obj)))
        if len(calls) == 20 and len(variables) == 10:
            break
    return dict(snapshot=model["snapshot"],calls=calls,variables=variables,notes="Deterministic source order: up to 10 linked + 10 unlinked callsites; 10 source-backed assignment bindings, skip synthetic/fixture/vendor objects. Manual verdicts must cite source. Not a random accuracy sample.")


def context(sources,obj):
    line=obj["location"]["line"] or 1
    lines=sources[obj["path"]].splitlines()
    return "\n".join(f"{i+1}: {lines[i]}" for i in range(max(0,line-3),min(len(lines),line+2)))


def evaluate_language(language, sources, output, tools, snapshot, timeout, repeats, dataflow):
    destination=output/language
    if not sources:
        return dict(status="no-input", language=language)
    env=tool_environment(tools["java"],destination)
    cpg=destination/"index-1.bin"
    measurements=[]
    for repeat in range(1,repeats+1):
        target=destination/f"index-{repeat}.bin"
        command=[tools["joern-parse"],str(destination/"input"),"--language", "PYTHONSRC" if language=="python" else "JSSRC", "--output",str(target)]
        result=run_process(command,destination,env,destination/f"index-{repeat}.log",timeout)
        result["artifactBytes"]=target.stat().st_size if target.exists() else None
        measurements.append(result)
        print(json.dumps({"language":language,"phase":"index","repeat":repeat,"status":result["status"],"seconds":result["seconds"]}),flush=True)
        if result["status"] != "complete":
            return dict(status=result["status"],language=language,indexing=measurements)
    query_file=destination/"joern-queries.json"
    command=[tools["joern"],"--script",str(HERE/"query_joern.sc"),"--param",f"cpgFile={cpg}","--param",f"outFile={query_file}","--param",f"withDataflow={str(dataflow).lower()}"]
    query_result=run_process(command,destination,env,destination/"query.log",timeout)
    if query_result["status"] != "complete":
        return dict(status="query-failed",language=language,indexing=measurements,query=query_result)
    export_dir=destination/"focused-export"
    export_dir.mkdir()
    graph_file=export_dir/'records.jsonl'
    export_result=run_process([tools['joern'],'--script',str(HERE/'export_joern.sc'),'--param',f'cpgFile={cpg}','--param',f'outFile={graph_file}'],destination,env,destination/"export.log",timeout)
    if export_result["status"] != "complete":
        return dict(status="export-failed",language=language,indexing=measurements,query=query_result,export=export_result)
    graph_files=list(export_dir.rglob("*.jsonl"))
    if not graph_files:
        return dict(status="export-format-unrecognized",language=language,indexing=measurements,query=query_result,export=export_result)
    raw=read_graphson(graph_files[0])
    model=normalize(raw,sources,snapshot,language,destination/"input")
    syntax=json.loads((output/'snapshot.json').read_text()).get('syntaxChecks',{})
    invalid={x['path'] for x in syntax.get('diagnostics',[]) if x['language']==language}
    model['coverage']['invalidSyntaxFiles']=sorted(invalid)
    model['coverage']['independentSyntaxCheck']=syntax.get(language,{}).get('status','not-recorded')
    for obj in model['objects']:
        obj['sourceStatus']='syntax-error' if obj['path'] in invalid else 'captured'
    for relation in model['relations']:
        if relation['evidence']['path'] in invalid:
            relation['status']='invalid-source'
    write_json(destination/"model.json",model)
    consumer=QueryIndex(model)
    write_json(destination/"consumer-queries.json",consumer.benchmark())
    write_json(destination/"source-review.json",select_review(model,sources))
    # The fixture expectation file is not a supported capture input; read the tracked oracle, never tool output.
    fixture_root=HERE.parents[1]/"tests"/"fixtures"/"joern"
    source_root=Path(json.loads((output/'snapshot.json').read_text())['project'])
    if source_root == fixture_root or source_root == fixture_root/language:
        expected=json.loads((fixture_root/"expected.json").read_text())["languages"][language]
        checks=fixture_checks(model,sources,expected)
        write_json(destination/"fixture-checks.json",checks)
        write_json(destination/'semantic-checks.json',check_semantics(model,sources))
    else:
        checks=None
    warnings=[]
    if syntax.get(language,{}).get('status')=='unavailable':
        warnings.append(dict(log='independent-source-syntax',text='Independent syntax checker unavailable; no claim that captured source is syntax-valid.'))
    warnings.extend(dict(log='independent-source-syntax',text=json.dumps(d,ensure_ascii=False)) for d in syntax.get('diagnostics',[]) if d['language']==language)
    if model['coverage']['missingFiles']:
        warnings.append(dict(log='coverage',text=f"{len(model['coverage']['missingFiles'])} captured files absent from exported declaration index; see model.coverage.missingFiles"))
    for log in (destination/"index-1.log", destination/"query.log", destination/"export.log"):
        for line in log.read_text(errors="replace").splitlines():
            if re.search(r"\b(ERROR|WARN)\b|Failed to parse|Error parsing|OutOfMemory|Skipping.*method",line):
                warnings.append(dict(log=log.name,text=line[:1000]))
    return dict(status="complete-with-diagnostics" if warnings else "complete",language=language,indexing=measurements,query=query_result,export=export_result,
                rawNodes=len(raw["nodes"]),rawEdges=len(raw["edges"]),normalized=model["coverage"],
                modelBytes=(destination/"model.json").stat().st_size,exportBytes=size(export_dir),
                fixture=checks,joernQueries=json.loads(query_file.read_text()),diagnostics=warnings)


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--project",required=True,type=Path)
    cli.add_argument("--joern",required=True,type=Path,help="joern executable or distribution root")
    cli.add_argument("--java",required=True,type=Path,help="Explicit java executable; no global Java changes")
    cli.add_argument("--output",required=True,type=Path,help="New output directory; existing results are never overwritten")
    cli.add_argument("--timeout",type=int,default=600)
    cli.add_argument("--repeats",type=int,default=2)
    cli.add_argument("--dataflow",action="store_true")
    args=cli.parse_args()
    if args.timeout < 1 or args.timeout > 600 or args.repeats not in (1,2):
        cli.error("timeout must be 1..600 seconds and repeats 1 or 2")
    output=args.output.expanduser().resolve()
    project=args.project.expanduser().resolve(strict=True)
    if output == project or (output.is_relative_to(project) and not output.is_relative_to(project/'.local')):
        cli.error("Output inside the analyzed project must be under .local")
    output.mkdir(parents=True,exist_ok=False)
    experiment_source=output/'experiment-source'
    experiment_source.mkdir()
    for path in HERE.iterdir():
        if path.suffix in ('.py','.sc'):
            (experiment_source/path.name).write_bytes(path.read_bytes())
    distribution=args.joern.expanduser().resolve()
    if distribution.is_file():
        distribution=distribution.parent
    tools={k:str(distribution/k) for k in ("joern","joern-parse","joern-export")}
    tools["java"]=str(args.java.expanduser().resolve())
    environment=tool_environment(tools["java"],output)
    preflight={name:run_process([path]+([] if name=='joern' else ['-version']),output,environment,output/f"{name}-version.log",30) for name,path in (("joern",tools["joern"]),("java",tools["java"]))}
    version_text=(output/"joern-version.log").read_text(errors="replace")
    if preflight["joern"]["status"] != "complete" or VERSION not in version_text or preflight["java"]["status"] != "complete":
        write_json(output/"results.json",dict(status="preflight-failed",requiredVersion=VERSION,preflight=preflight))
        cli.exit(1,"Pinned Joern / Java preflight failed; see output logs.\n")
    project,entries,originals,languages,manifest=prepare(project,output)
    results=dict(version=1,engineVersion=VERSION,project=str(project),snapshot=manifest["snapshot"],
                 experimentFiles={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.iterdir() if p.suffix in ('.py','.sc')},
                 startedAt=datetime.now(timezone.utc).isoformat(),platform=platform.platform(),
                 tools=tools,preflight=preflight,toolInstalledBytes=size(distribution),
                 javaInstalledBytes=size(Path(tools["java"]).parent.parent),languages={})
    write_json(output/"results.json",results)
    for language,sources in languages.items():
        try:
            result=evaluate_language(language,sources,output,tools,manifest["snapshot"],args.timeout,args.repeats,args.dataflow)
        except Exception as exc:
            result=dict(status="adapter-failed",error=f"{type(exc).__name__}: {exc}")
        results["languages"][language]=result
        write_json(output/"results.json",results)
    results["changedInputs"]=verify_inputs(project,entries,originals)
    results["validForCurrentProject"]=not results["changedInputs"]
    failed=[name for name,value in results['languages'].items() if value['status'] not in ('complete','complete-with-diagnostics','no-input')]
    results['status']='stale-input' if results['changedInputs'] else 'tool-failed' if failed else 'completed'
    results["completedAt"]=datetime.now(timezone.utc).isoformat()
    write_json(output/"results.json",results)
    print(json.dumps({"output":str(output),"languages":{k:v["status"] for k,v in results["languages"].items()},"changedInputs":results["changedInputs"]}),flush=True)
    if results['changedInputs']:
        cli.exit(2,'Captured inputs changed; results describe the preserved snapshot only.\n')
    if failed:
        cli.exit(1,'Tool stages failed: '+', '.join(failed)+'; raw logs and results retained.\n')


if __name__ == "__main__":
    main()
