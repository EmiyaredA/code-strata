"""Snapshot-only symbol annotations. Never infer names from diagram prose."""
import copy
import threading
from collections import OrderedDict

from code_analysis.model import FUNCTIONS
from code_analysis.service import CodeSession
from .snapshots import fingerprint
from .diagrams import snapshot_file


def contains(outer, inner):
    return tuple(outer['start']) <= tuple(inner['start']) and tuple(inner.get('end', inner['start'])) <= tuple(outer['end'])


def symbol(node):
    return {k: node[k] for k in ('id', 'name', 'kind', 'path', 'range')}


def annotate(refs, session, store):
    result = []
    for original in refs:
        ref = copy.deepcopy(original)
        span = ref.get('range') or dict(start=[ref['startLine'], 0], end=[ref['endLine'], 0])
        functions = [n for n in session.symbols_by_path.get(ref['path'], []) if n['kind'] in FUNCTIONS and contains(n['range'], span)]
        if functions:
            owner = min(functions, key=lambda n: (n['range']['end'][0]-n['range']['start'][0], n['range']['end'][1]-n['range']['start'][1]))
            ref['symbol'] = symbol(owner)
        ref['association'] = 'definition' if ref.get('locationKind') == 'definition' else 'callsite' if ref.get('locationKind') == 'call' else 'source'
        result.append(ref)
        # A broad source read is not permission to present every nested call as
        # this diagram element's target. Only exact call evidence/small sites.
        if ref.get('locationKind') == 'definition' or ref['endLine']-ref['startLine'] > 2:
            continue
        calls = [n for n in session.by_id.values() if n['kind'] == 'call' and n['path'] == ref['path'] and contains(span, n['range'])]
        # read_source often uses whole lines with end column zero.
        if not calls:
            calls = [n for n in session.by_id.values() if n['kind'] == 'call' and n['path'] == ref['path'] and ref['startLine'] <= n['range']['start'][0] <= ref['endLine']]
        if calls and ref.get('locationKind') == 'source':
            ref['association'] = 'callsite'
        for call in calls:
            target = session.by_id.get(call.get('targetId'))
            if not target or target['kind'] not in FUNCTIONS:
                continue
            try:
                captured = snapshot_file(store, ref['snapshotId'], target['path'])
            except LookupError:
                continue
            result.append(dict(id=ref['id'], relatedTo=ref['id'], snapshotId=ref['snapshotId'], path=target['path'],
                startLine=target['range']['start'][0], endLine=target['range']['end'][0], range=target['range'],
                contentHash=captured['contentHash'], locationKind='definition', association='target-definition',
                status=call.get('status', 'candidate'), symbol=symbol(target)))
    return list({(r['path'], r['startLine'], r['endLine'], r.get('association'), r.get('symbol', {}).get('id')): r for r in result}.values())


def annotate_model(model, session, store):
    enriched = copy.deepcopy(model)
    for item in enriched['nodes'] + enriched['edges']:
        if item.get('role') not in ('start', 'end', 'fork', 'join', 'merge'):
            item['evidence'] = annotate(item.get('evidence', []), session, store)
    enriched['evidence'] = list({(r['id'], r['path'], r['startLine'], r.get('association')): r
        for r in enriched.get('evidence', []) + [r for e in enriched['nodes']+enriched['edges'] for r in e.get('evidence', [])]}.values())
    enriched['sourceMapVersion'] = 1
    return enriched


class SourceMaps:
    def __init__(self, store):
        self.store, self.lock, self.entries = store, threading.RLock(), OrderedDict()
        self.sessions, self.build_slots = OrderedDict(), threading.BoundedSemaphore(2)

    def get(self, project, identifier, revision=None, retry=False):
        document = self.store.diagram(project, identifier, revision)
        key = (identifier, document['revision'], document['snapshotId'])
        with self.lock:
            if retry and self.entries.get(key, {}).get('status') == 'failed':
                del self.entries[key]
                self.sessions.pop(document['snapshotId'], None)
            if key not in self.entries:
                entry = dict(status='building', elements={}, snapshotId=document['snapshotId'])
                self.entries[key] = entry
                threading.Thread(target=self._build, args=(document, entry), daemon=True, name='uml-source-map').start()
                while len(self.entries) > 16:
                    self.entries.popitem(last=False)
            self.entries.move_to_end(key)
            return copy.deepcopy(self.entries[key])

    def _build(self, document, entry):
        try:
            if document['model'].get('sourceMapVersion') == 1:
                with self.lock:
                    entry.update(status='ready', elements={e['id']:e.get('evidence',[]) for e in document['model']['nodes']+document['model']['edges']})
                return
            payload = self.store.snapshot(document['snapshotId'])
            if fingerprint(payload['data']) != document['snapshotId']:
                result = dict(status='unavailable', message='分析器已变化；保留历史源码，函数标签需根据当前代码重新生成。', elements={})
            else:
                with self.lock:
                    sid = document['snapshotId']
                    if sid not in self.sessions:
                        self.sessions[sid] = (CodeSession(payload['data'], payload['context']), threading.Lock())
                    session, session_lock = self.sessions[sid]
                    self.sessions.move_to_end(sid)
                    while len(self.sessions) > 4:
                        self.sessions.popitem(last=False)
                with session_lock, self.build_slots:
                    if session.model is None:
                        session.build()
                if session.status == 'failed':
                    raise ValueError('源码索引构建失败')
                model = annotate_model(document['model'], session, self.store)
                result = dict(status='ready', elements={e['id']: e.get('evidence', []) for e in model['nodes']+model['edges']})
        except Exception as exc:
            result = dict(status='failed', message=str(exc)[:300], elements={})
        with self.lock:
            entry.update(result)
