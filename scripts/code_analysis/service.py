"""Session-local semantic indexing and bounded, snapshot-scoped graph queries."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
try:
    import resource
except ImportError:
    resource = None
from .model import empty, merge, edge, FUNCTIONS, VARIABLES
from node_runtime import resolve_node

SCRIPTS = Path(__file__).resolve().parent.parent
MAX_NODES, MAX_EDGES = 100, 300


def run_language(context, language, mode='index', function=None):
    files = [f for f in context['files'] if (f['language'] == 'python') == (language == 'python')
             and f.get('captureStatus') == 'captured' and f.get('parseStatus') == 'parsed']
    if function:
        files = [f for f in files if f['id'] == function['path']]
    if not files: return empty()
    request = dict(files=files, configs=context.get('configs', {}), imports=context.get('imports', []), mode=mode, function=function)
    env = dict(os.environ)
    for key in ('NODE_OPTIONS', 'NODE_PATH', 'PYTHONPATH', 'PYTHONSTARTUP'):
        env.pop(key, None)
    if language == 'python':
        command = [sys.executable, '-I', '-c', 'import sys; sys.path.insert(0, sys.argv[1]); from code_analysis.worker import main; main()', str(SCRIPTS)]
    else:
        runtime = context.get('runtime') or resolve_node()
        if runtime['status'] != 'ready':
            raise ValueError(runtime['message'])
        command = [runtime['executable'], '--max-old-space-size=2048', str(SCRIPTS / 'analyze-code.cjs')]
    result = subprocess.run(command, input=json.dumps(request, ensure_ascii=False), text=True,
                            capture_output=True, timeout=60, cwd=SCRIPTS, env=env)
    if result.returncode:
        raise ValueError(f'{language} 分析器失败（{result.returncode}）：{result.stderr[-1200:]}')
    return json.loads(result.stdout)


class CodeSession:
    def __init__(self, data, context):
        self.data, self.context = data, context
        self.status = 'idle'
        self.model = None
        self.lock = threading.Lock()
        self.logic_cache = {}
        self.logic_lock = threading.Lock()
        self.metrics = {}
        self.host_resources = None

    def build(self):
        parts = []
        for language in ('javascript', 'python'):
            start = time.perf_counter()
            try:
                part = run_language(self.context, language)
                self.metrics[language] = dict(status='ready', durationMs=round((time.perf_counter() - start) * 1000, 2), engine=part.get('engine'), resources=part.get('resources'))
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                message = '超过 60 秒分析时限' if isinstance(exc, subprocess.TimeoutExpired) else str(exc)
                part = empty()
                part['diagnostics'].append(dict(kind='engine', language=language, message=message))
                self.metrics[language] = dict(status='failed', durationMs=round((time.perf_counter()-start)*1000, 2), message=message)
            parts.append(part)
        model = merge(parts)
        for file in self.data.get('inventory', self.data['files']):
            if file.get('parseStatus') != 'parsed':
                model['diagnostics'].append(dict(kind='coverage', path=file['id'], message=file.get('parseReason') or f"此文件未进入语义分析：{file.get('parseStatus', 'unsupported')}"))
        with self.lock:
            self.model = model
            self.by_id = {n['id']: n for n in model['nodes']}
            self.file_nodes = {n['path']: n for n in model['nodes'] if n['kind'] == 'file'}
            # Inventory-only files remain navigable without claiming semantic support.
            for f in self.data.get('inventory', self.data['files']):
                if f['id'] not in self.file_nodes and f.get('category') != 'config':
                    obj = dict(id='file:' + f['id'], kind='file', name=f['id'], path=f['id'], language=f.get('language'), status='unsupported', range=dict(start=[1,0], end=[1,0]), reason=f.get('parseReason') or '源码未解析或不支持该语言')
                    self.file_nodes[f['id']] = obj
                    self.by_id[obj['id']] = obj
            self.incoming, self.outgoing, self.children, self.references = {}, {}, {}, {}
            self.symbols_by_path, self.variables_by_owner, self.refs_by_function, self.calls_by_function = {}, {}, {}, {}
            self.search_nodes = []
            for n in self.by_id.values():
                if n['kind'] in FUNCTIONS | VARIABLES | {'file','class'}: self.search_nodes.append(n)
                if n['kind'] in FUNCTIONS | {'class'}: self.symbols_by_path.setdefault(n['path'], []).append(n)
                if n['kind'] in VARIABLES: self.variables_by_owner.setdefault(n.get('functionId') or n.get('ownerId'), []).append(n)
                if n['kind'] == 'reference': self.refs_by_function.setdefault(n.get('functionId'), []).append(n)
                if n['kind'] == 'call': self.calls_by_function.setdefault(n.get('functionId'), []).append(n)
            for r in model['relations']:
                self.incoming.setdefault(r['target'], []).append(r)
                self.outgoing.setdefault(r['source'], []).append(r)
                if r['kind'] == 'contains': self.children.setdefault(r['source'], []).append(r['target'])
                if r['kind'] == 'references': self.references.setdefault(r['target'], []).append(r['source'])
            self.host_resources = dict(peakRssBytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024)) if resource else None
            self.status = 'partial' if model['diagnostics'] else 'ready'
            if not model['nodes'] and any(x['status'] == 'failed' for x in self.metrics.values()): self.status = 'failed'

    def ensure(self):
        with self.lock:
            if self.status == 'idle':
                self.status = 'building'
                threading.Thread(target=self._safe_build, daemon=True, name='code-index').start()
            return self.status

    def _safe_build(self):
        try: self.build()
        except Exception as exc:
            with self.lock:
                self.model = empty()
                self.model['diagnostics'] = [dict(kind='engine', message=str(exc))]
                self.status = 'failed'

    def export(self):
        if self.model is None: self.build()
        return dict(**self.model, snapshotId=self.data['snapshot']['id'], status=self.status,
                    engines=self.metrics, hostResources=self.host_resources, coordinates='1-based lines; 0-based UTF-16 columns; end-exclusive',
                    limitations=['静态目标不代表实际运行调用', '变量引用不代表赋值到使用的数据流', '逻辑关系为结构化简图，不是完整控制流'])

    def query(self, body):
        for field in ('view','focusId','groupId','text'):
            if field in body and (not isinstance(body[field], str) or len(body[field]) > 2000):
                raise ValueError(f'{field} 参数无效')
        view = body.get('view', 'files')
        if view not in ('files','functions','logic','references','search','symbols'):
            raise ValueError('未知的代码视图')
        limit = body.get('limit', MAX_NODES)
        offset = body.get('offset', 0)
        edge_offset = body.get('edgeOffset', 0)
        hops = body.get('hops', 1)
        if any(isinstance(v, bool) or not isinstance(v, int) for v in (limit,offset,hops,edge_offset)) or not 1 <= limit <= MAX_NODES or offset < 0 or edge_offset < 0 or not 1 <= hops <= 5:
            raise ValueError('查询范围无效')
        status = self.ensure()
        base = dict(version=1, snapshotId=self.data['snapshot']['id'], status=status, view=view)
        if status == 'building': return dict(**base, nodes=[], relations=[], retryAfterMs=350)
        if status == 'failed': return dict(**base, nodes=[], relations=[], diagnostics=self.model['diagnostics'])
        focus = body.get('focusId')
        if focus in self.file_nodes: focus = self.file_nodes[focus]['id']
        selected = self.by_id.get(focus)
        # A file is a scope, not a function-call entry node. Pick a visible default
        # function and disclose the choice; callers can explicitly select another.
        scope_file = selected['path'] if selected and selected['kind'] == 'file' else None
        default_focus = None
        if view == 'functions' and scope_file:
            functions = [n for n in self.symbols_by_path.get(scope_file, []) if n['kind'] in FUNCTIONS]
            if functions:
                stem = Path(scope_file).stem
                def score(n):
                    top_level = self.by_id.get(n.get('ownerId'), {}).get('kind') == 'file'
                    preferred = n['name'] in ('main', stem, 'run', 'start')
                    span = n['range']['end'][0] - n['range']['start'][0]
                    return (top_level, preferred, n['name'] == stem, span, -n['range']['start'][0])
                selected = max(functions, key=score)
                focus = selected['id']
                default_focus = dict(reason='按名称与顶层函数体范围选作浏览焦点；不表示运行时入口', name=selected['name'])
        candidates, relations = [], []
        if view == 'search':
            text = str(body.get('text', '')).strip().casefold()[:200]
            if text:
                candidates = [n for n in self.search_nodes if text in n['name'].casefold() or text in n['path'].casefold()]
        elif view == 'files':
            wanted = set()
            if body.get('groupId'):
                group = next((g for g in self.data['groups'] if g['id'] == body['groupId']), None)
                if not group: raise ValueError('架构分组不存在')
                wanted.update(group['files'])
            elif selected: wanted.add(selected['path'])
            else: wanted.update(self.file_nodes)
            for _ in range(hops):
                frontier = set(wanted)
                wanted.update(r['to'] for r in self.data['imports'] if r['from'] in frontier)
                wanted.update(r['from'] for r in self.data['imports'] if r['to'] in frontier)
            candidates = [n for p,n in self.file_nodes.items() if p in wanted]
            for r in self.data['imports']:
                a,b = self.file_nodes.get(r['from']), self.file_nodes.get(r['to'])
                if a and b and r['from'] in wanted and r['to'] in wanted:
                    relations.append(edge('imports', a['id'], b['id'], siteId=f"{r['from']}:{r['line']}:{r['specifier']}", path=r['from'], range=dict(start=[r['line'],0],end=[r['line'],0]), evidence=r))
        elif view in ('symbols', 'functions'):
            if not selected: raise ValueError('焦点对象不存在')
            if selected['kind'] == 'file' or view == 'symbols':
                candidates = list(self.symbols_by_path.get(selected['path'], []))
                wanted = {n['id'] for n in candidates}
                if view == 'functions':
                    for _ in range(hops):
                        touching = [r for x in tuple(wanted) for r in self.incoming.get(x, []) + self.outgoing.get(x, []) if r['kind'] == 'calls']
                        wanted.update(r[k] for r in touching for k in ('source', 'target'))
                    candidates = [self.by_id[x] for x in wanted if x in self.by_id]
                    relations = [r for x in wanted for r in self.outgoing.get(x, []) if r['kind'] == 'calls' and r['target'] in wanted]
            else:
                wanted = {focus}
                for _ in range(hops):
                    touching = [r for x in tuple(wanted) for r in self.incoming.get(x, []) + self.outgoing.get(x, []) if r['kind'] == 'calls']
                    wanted.update(r[k] for r in touching for k in ('source','target'))
                candidates = [self.by_id[x] for x in wanted if x in self.by_id]
                # Unresolved calls are retained as source-backed call-site nodes.
                candidates.extend(n for n in self.calls_by_function.get(focus, []) if not n.get('targetId'))
                for n in candidates:
                    if n['kind'] == 'call': relations.append(edge('unresolved-call', focus, n['id'], siteId=n['id'], status='unresolved'))
                relations.extend(r for x in wanted for r in self.outgoing.get(x, []) if r['kind'] == 'calls' and r['target'] in wanted)
        elif view == 'references':
            if not selected or selected['kind'] not in VARIABLES: raise ValueError('请选择变量或参数')
            candidates = [selected] + [self.by_id[x] for x in self.references.get(focus, [])]
            relations = [r for r in self.incoming.get(focus, []) if r['kind'] == 'references']
        elif view == 'logic':
            if not selected or selected['kind'] not in FUNCTIONS: raise ValueError('请选择有源码函数体的函数')
            with self.logic_lock:
                if focus not in self.logic_cache:
                    try:
                        self.logic_cache[focus] = run_language(self.context, 'python' if selected['language'] == 'python' else 'javascript', 'logic', selected)
                    except (OSError, ValueError, subprocess.SubprocessError) as exc:
                        failure = dict(base); failure['status'] = 'failed'
                        return dict(**failure, nodes=[], relations=[], diagnostics=[dict(kind='logic', message=str(exc))])
                detail = self.logic_cache[focus]
            candidates = detail['nodes']
            relations = detail['relations']
        if view == 'functions':
            grouped, rest = {}, []
            for r in relations:
                if r['kind'] != 'calls':
                    rest.append(r)
                    continue
                key = (r['source'], r['target'], r.get('status'))
                if key not in grouped:
                    grouped[key] = edge('calls', r['source'], r['target'], siteId=r.get('siteId'), status=r.get('status'), path=r.get('path'), range=r.get('range'), sites=[], siteCount=0)
                item = grouped[key]
                item['siteCount'] += 1
                if len(item['sites']) < 100: item['sites'].append(dict(id=r.get('siteId'), path=r.get('path'), range=r.get('range')))
            relations = rest + list(grouped.values())
        # Deterministic windows keep browser graphs bounded, including after expansion.
        candidates = list({n['id']:n for n in candidates}.values())
        candidates.sort(key=lambda n: (n['id'] != focus, n['path'], n['range']['start'], n['kind'], n['id']))
        anchor = selected if selected and selected['id'] in {n['id'] for n in candidates} and limit > 1 else None
        window = [n for n in candidates if not anchor or n['id'] != anchor['id']]
        page_size = limit - (1 if anchor else 0)
        page = ([anchor] if anchor else []) + window[offset:offset+page_size]
        remaining = max(0,len(window)-offset-page_size)
        page_ids = {n['id'] for n in page}
        visible_edges = list({r['id']:r for r in relations if r['source'] in page_ids and r['target'] in page_ids}.values())
        variables = list(self.variables_by_owner.get(focus, [])) if selected else []
        if view == 'logic' and selected:
            # Captured bindings belong to enclosing scopes; include them explicitly.
            captured = {n.get('symbolId') for n in self.refs_by_function.get(focus, [])}
            owned = {n['id'] for n in variables}
            variables += [self.by_id[x] for x in sorted(captured - {None}) if x not in owned and x in self.by_id and self.by_id[x]['kind'] in VARIABLES]
        symbols = self.symbols_by_path.get(selected['path'], [])[:100] if selected else []
        if view == 'files' and selected: symbols = symbols[:100]
        variable_ids = {n['id'] for n in variables}
        refs = [n for n in self.refs_by_function.get(focus, []) if n.get('symbolId') in variable_ids]
        # Separate detail budgets are explicit; selecting a variable can page all its occurrences.
        diagnostics = self.model['diagnostics']
        return dict(**base, focus=selected, scopeFile=scope_file, defaultFocus=default_focus, unresolvedCallCount=sum(not n.get('targetId') for n in self.calls_by_function.get(focus, [])), nodes=page, relations=visible_edges[edge_offset:edge_offset+MAX_EDGES],
                    totalNodes=len(candidates), offset=offset, pageSize=page_size, remaining=remaining, nextOffset=offset+page_size if remaining else None,
                    totalEdges=len(relations), edgeOffset=edge_offset, edgeRemaining=max(0,len(visible_edges)-edge_offset-MAX_EDGES), truncated=bool(remaining or offset or len(visible_edges)>MAX_EDGES),
                    symbols=symbols, variables=variables[:100], references=refs[:300], detailTruncated=len(variables)>100 or len(refs)>300,
                    diagnostics=diagnostics[:100], diagnosticCount=len(diagnostics), engines=self.metrics,
                    note='结构化逻辑简图；不表示完整控制流。变量连线表示符号引用。' if view == 'logic' else '静态调用目标不代表实际运行调用。')
