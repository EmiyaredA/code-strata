"""Reproduce real-source measurements and a deterministic manual review worksheet."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics
import time
from scan import scan_project
from code_analysis.service import CodeSession
from code_analysis.model import FUNCTIONS, VARIABLES


def evaluate(project, output, node=None):
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    context = {}
    started = time.perf_counter()
    data = scan_project(project, node=node, snapshot_context=context)
    capture_ms = (time.perf_counter()-started)*1000
    files = {f['id']:f for f in context['files']}
    session = CodeSession(data, context)
    started = time.perf_counter()
    model = session.export()
    index_ms = (time.perf_counter()-started)*1000
    def source(n):
        f = files[n['path']]
        line = n['range']['start'][0]
        lines = f['content'].splitlines()
        return dict(path=n['path'], range=n['range'], hash=f['hash'],
                    excerpt='\n'.join(f'{i+1}: {lines[i]}' for i in range(max(0,line-3),min(len(lines),line+3))))
    audit = dict(snapshotId=data['snapshot']['id'], project=data['project'], languages={})
    measurements = {}
    for language in ('javascript', 'python'):
        is_lang = lambda n: (n['language']=='python') == (language=='python')
        source_nodes = [n for n in model['nodes'] if is_lang(n) and files[n['path']].get('category') == 'source' and not {'_vendor','vendor'}.intersection(Path(n['path']).parts)]
        def rank(n):
            preferred = n['path'].startswith(('web/src/', 'desktop/src/', 'backend/app/', 'assets/board-source/src/'))
            return (not preferred, n['path'], n['range']['start'], n['id'])
        def diversified(items, count):
            selected, per_file = [], Counter()
            for n in sorted(items, key=rank):
                if per_file[n['path']] >= 2: continue
                selected.append(n); per_file[n['path']] += 1
                if len(selected) == count: break
            return selected
        calls = sorted([n for n in source_nodes if n['kind']=='call'],key=rank)
        # Stratify by linked/unlinked cases; do not present this as a random accuracy estimate.
        linked = diversified([n for n in calls if n.get('targetId')], 10)
        unlinked = diversified([n for n in calls if not n.get('targetId')], 10)
        chosen = linked+unlinked
        if len(chosen)<20: chosen += [n for n in calls if n not in chosen][:20-len(chosen)]
        call_records=[]
        for n in chosen:
            target = session.by_id.get(n.get('targetId'))
            call_records.append(dict(id=n['id'], name=n['name'], status=n['status'], source=source(n), target=dict(name=target['name'], kind=target['kind'], **source(target)) if target else None, reviewStatus='pending', finding=''))
        variables = diversified([n for n in source_nodes if n['kind'] in VARIABLES and not n.get('imported') and session.references.get(n['id'])],10)
        variable_records=[]
        for n in variables:
            refs=[session.by_id[x] for x in session.references.get(n['id'],[])]
            variable_records.append(dict(id=n['id'], name=n['name'], kind=n['kind'], definition=source(n), scope=source(session.by_id[n['ownerId']]), references=[dict(name=r['name'],access=r['access'],capture=r.get('capture'),**source(r)) for r in refs[:12]], referenceCount=len(refs), reviewStatus='pending',finding=''))
        audit['languages'][language]=dict(calls=call_records,variables=variable_records)
        functions=[n for n in source_nodes if n['kind'] in FUNCTIONS]
        timings=[]
        for n in functions[:20]:
            start=time.perf_counter();session.query(dict(view='functions',focusId=n['id']));timings.append((time.perf_counter()-start)*1000)
        logic_times=[]
        for n in functions[:3]:
            start=time.perf_counter();session.query(dict(view='logic',focusId=n['id']));logic_times.append((time.perf_counter()-start)*1000)
        sorted_times=sorted(timings)
        measurements[language]=dict(engine=session.metrics[language], nodes=len([n for n in model['nodes'] if is_lang(n)]),calls=dict(Counter(n['status'] for n in calls)),
                                    reviewedCalls=len(call_records), reviewedVariables=len(variable_records),
                                    functionQuery=dict(samples=len(timings),p50Ms=statistics.median(timings) if timings else None,p95Ms=sorted_times[max(0,__import__('math').ceil(.95*len(sorted_times))-1)] if timings else None),
                                    coldLogicMs=logic_times)
    with (destination/'model.json').open('w', encoding='utf8') as stream:
        json.dump(model, stream, ensure_ascii=False)
    snapshot = dict(snapshot=data['snapshot'], files=[dict(id=f['id'],hash=f['hash'],content=f['content']) for f in context['files']])
    (destination/'source-snapshot.json').write_text(json.dumps(snapshot,ensure_ascii=False))
    (destination/'source-review.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2))
    summary=dict(snapshot=data['snapshot'],status=model['status'], captureMs=round(capture_ms,2),indexMs=round(index_ms,2),
                 hostResources=model.get('hostResources'),modelJsonBytes=(destination/'model.json').stat().st_size,nodes=len(model['nodes']),relations=len(model['relations']),
                 diagnostics=model['diagnostics'][:100],diagnosticCount=len(model['diagnostics']), languages=measurements)
    (destination/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in summary.items() if k not in ('diagnostics',)},ensure_ascii=False))

if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--project',required=True);cli.add_argument('--output',required=True);cli.add_argument('--node')
    a=cli.parse_args();evaluate(a.project,a.output,a.node)
