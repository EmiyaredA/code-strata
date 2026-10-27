"""Source-anchored fixture checks beyond node counts. Static results, not execution."""

from collections import defaultdict, deque


def reachable(start, goals, adjacency, blocked=frozenset()):
    queue=deque([start]);seen=set()
    while queue:
        node=queue.popleft()
        if node in seen or node in blocked:
            continue
        if node in goals:
            return True
        seen.add(node)
        queue.extend(adjacency[node])
    return False


def check_semantics(model,sources):
    objects={x['id']:x for x in model['objects']}
    cfg=defaultdict(list)
    for edge in model['relations']:
        if edge['kind']=='controlFlow':cfg[edge['source']].append(edge['target'])
    worker=next((p for p in sources if p.endswith(('worker.ts','worker.py'))),None)
    if not worker:return {'status':'not-a-fixture'}
    markers={line.split('CASE ',1)[1].strip():i for i,line in enumerate(sources[worker].splitlines(),1) if 'CASE ' in line}
    early=markers['early-return'];finally_line=markers['finally']
    returns=[x for x in objects.values() if x['path']==worker and x['label']=='RETURN' and x['location']['line']==early]
    cleanup={x['id'] for x in objects.values() if x['path']==worker and x['kind']=='callsite' and x['name']=='cleanup' and x['location']['line']==finally_line}
    exit_nodes={x['id'] for x in objects.values() if x['label']=='METHOD_RETURN' and any(x.get('owner')==r.get('owner') for r in returns)}
    finally_results=[]
    for ret in returns:
        bypass=reachable(ret['id'],exit_nodes,cfg,cleanup)
        finally_results.append(dict(path=worker,returnLine=early,finallyLine=finally_line,
                                    returnCode=ret['code'],canReachCleanup=reachable(ret['id'],cleanup,cfg),
                                    reachesExitWithoutCleanup=bypass,
                                    status='unwind-not-represented' if bypass else 'no-bypass-found',
                                    directSuccessors=[dict(label=objects[t]['label'],line=objects[t]['location']['line'],code=objects[t]['code']) for t in cfg[ret['id']]]))
    first,last,read=(markers[x] for x in ('flow-first-write','flow-last-write','flow-read'))
    reaching=[]
    for edge in model['relations']:
        if edge['kind']!='dataDependency':continue
        a,b=objects[edge['source']],objects[edge['target']]
        if a['path']==worker and b['path']==worker and a['name']=='value' and b['name']=='value' and b['location']['line']==read:
            reaching.append(dict(sourceLine=a['location']['line'],targetLine=read,variable=edge.get('variable')))
    scopes=[]
    for var in objects.values():
        if var['path']==worker and var['kind']=='variable' and var['name']=='key':
            refs=[objects[e['source']] for e in model['relations'] if e['kind']=='references' and e['target']==var['id']]
            owner=objects.get(var.get('owner'),{})
            scopes.append(dict(id=var['id'],declarationLine=var['location']['line'],owner=owner.get('fullName'),synthetic=var['synthetic'],references=[r['location']['line'] for r in refs]))
    return dict(status='evaluated',finallyOnEarlyReturn=finally_results,
                overwrittenValue=dict(firstWrite=first,lastWrite=last,read=read,reachingEdges=reaching,
                                      lastWriteReachesRead=any(x['sourceLine']==last for x in reaching),
                                      overwrittenFirstWriteReachesRead=any(x['sourceLine']==first for x in reaching)),
                keyScopes=scopes,
                limits=['This validates one reaching-definition fixture, not general dataflow correctness.',
                        'Closure/global binding proxies are retained; REF edges alone do not establish canonical source bindings.',
                        'Node presence for await/yield/loops does not verify suspension, cancellation or all exceptional paths.'])
