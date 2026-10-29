"""Typed UML documents and immutable, project-owned source evidence.

Source citations prove where an interpretation came from; they do not make an
AI interpretation an analyzer fact. Canonical call status is never AI supplied.
"""
import hashlib
import json
from pathlib import Path
import re
import uuid
from datetime import datetime, timezone


KINDS = ('activity', 'sequence', 'class', 'component', 'state', 'usecase', 'deployment')
ROLES = {
    'activity': {'action', 'decision', 'merge', 'start', 'end', 'fork', 'join', 'note'},
    'sequence': {'participant', 'actor', 'boundary', 'control', 'entity', 'note'},
    'class': {'class', 'interface', 'enum', 'package', 'note'},
    'component': {'component', 'interface', 'package', 'note'},
    'state': {'state', 'choice', 'start', 'end', 'fork', 'join', 'note'},
    'usecase': {'actor', 'usecase', 'system', 'note'},
    'deployment': {'device', 'execution', 'artifact', 'component', 'note'},
}
EDGE_ROLES = {'flow', 'message', 'return', 'async', 'create', 'destroy', 'association', 'dependency',
              'inheritance', 'implementation', 'composition', 'aggregation', 'transition', 'include', 'extend', 'communication'}
EDGE_TYPES = {
    'activity': {'flow'}, 'sequence': {'message','return','async','create','destroy'},
    'class': {'association','dependency','inheritance','implementation','composition','aggregation'},
    'component': {'association','dependency','implementation','composition','aggregation','communication'},
    'state': {'transition','flow'}, 'usecase': {'association','include','extend','inheritance'},
    'deployment': {'communication','dependency','association','composition'},
}
DECORATIVE = {'start', 'end', 'fork', 'join', 'merge'}


class DiagramConflict(ValueError):
    pass


def stamp():
    return datetime.now(timezone.utc).isoformat()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def text(value, label, maximum=200, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ValueError(label + '无效或过长')
    if re.search(r'<\s*/?\s*(?:script|iframe|object|embed|svg|style|img)\b|javascript:', value, re.I):
        raise ValueError(label + '不能包含活动内容')
    return value


def snapshot_file(store, snapshot_id, path):
    """Read exactly the captured blob, never a caller-controlled disk path."""
    with store.connect() as db:
        row = db.execute('SELECT project,payload FROM snapshots WHERE id=?', (snapshot_id,)).fetchone()
        if not row:
            raise LookupError('源码快照不存在')
        payload = json.loads(row['payload'])
        context = payload['context']
        item = next((f for f in context['files'] + context.get('sourceFiles', []) if f['id'] == path), None)
        digest = item.get('contentHash') if item else context.get('configs', {}).get(path)
        blob = db.execute('SELECT content FROM blobs WHERE hash=?', (digest,)).fetchone() if digest else None
        if not blob:
            raise LookupError('该文件没有可读取的快照正文')
        return dict(path=path, contentHash=digest, content=blob['content'], project=row['project'])


def source_evidence(store, run_id, snapshot_id, source):
    start, end = source['startLine'], source['endLine']
    identifier = 'source:' + hashlib.sha256(f'{snapshot_id}:{source["path"]}:{start}:{end}'.encode()).hexdigest()[:32]
    item = dict(id=identifier, kind='source', path=source['path'], range=dict(start=[start, 0], end=[end, 0]),
                locationKind='source', status='inferred')
    store.record_facts(run_id, dict(nodes=[item]))
    return identifier


def validate_diagrams(store, run_id, snapshot_id, project, args, target=None, require_target=False):
    if not isinstance(args, dict) or set(args) != {'diagrams'} or not isinstance(args['diagrams'], list) or not 1 <= len(args['diagrams']) <= 12:
        raise ValueError('每轮提交 1–12 张 UML 图')
    facts = {**store.facts(run_id, 'node'), **store.facts(run_id, 'relation')}
    files, results, updates = {}, [], set()

    def citations(ids, optional=False):
        if not isinstance(ids, list) or len(ids) > 30 or any(not isinstance(x, str) for x in ids) or len(set(ids)) != len(ids) or (not optional and not ids):
            raise ValueError('语义元素必须附带本轮查询或源码读取返回的 evidenceIds')
        result = []
        for identifier in ids:
            fact = facts.get(identifier)
            if not fact:
                raise ValueError('图引用了未经本轮工具提供的依据：' + identifier)
            sites = fact.get('sites') or [fact]
            for site in sites:
                path = site.get('path') or fact.get('path')
                if not path:
                    raise ValueError('此依据没有源码位置，请使用 read_source 补充依据')
                if path not in files:
                    files[path] = snapshot_file(store, snapshot_id, path)
                file = files[path]
                if file['project'] != project:
                    raise ValueError('源码不属于当前项目')
                span = site.get('range') or fact.get('range') or dict(start=[1, 0], end=[1, 0])
                total = len(file['content'].split('\n'))
                start, end = span['start'][0], span.get('end', span['start'])[0]
                if type(start) is not int or type(end) is not int or not 1 <= start <= end <= total:
                    raise ValueError('依据行号超出源码快照')
                result.append(dict(id=identifier, snapshotId=snapshot_id, path=path,
                    range=span, startLine=start, endLine=end,
                    contentHash=file['contentHash'], status=fact.get('status', 'inferred'),
                    locationKind=fact.get('locationKind') or ('call' if fact.get('kind') in ('calls', 'unresolved-call', 'call') else 'definition' if fact.get('kind') in ('function', 'method', 'constructor', 'class') else 'source')))
        return result

    for value in args['diagrams']:
        if not isinstance(value, dict) or set(value) - {'id', 'expectedRevision', 'type', 'title', 'purpose', 'nodes', 'edges', 'explanation'}:
            raise ValueError('UML 图字段无效')
        kind = value.get('type')
        if kind not in KINDS:
            raise ValueError('不支持的 UML 类型')
        identifier, expected = value.get('id'), value.get('expectedRevision')
        if identifier:
            store.diagram(project, identifier)
            if type(expected) is not int or expected < 1:
                raise ValueError('更新必须提供 expectedRevision')
            if identifier in updates:
                raise ValueError('同轮不能重复更新同一张图')
            updates.add(identifier)
            if target and (identifier != target['id'] or expected != target['expectedRevision']):
                raise ValueError('更新目标与本轮指定图不一致')
        elif expected is not None:
            raise ValueError('新图不能指定版本')
        nodes, edges = value.get('nodes'), value.get('edges')
        if not isinstance(nodes, list) or not 1 <= len(nodes) <= 100 or not isinstance(edges, list) or len(edges) > 300:
            raise ValueError('每图最多 100 个节点、300 条关系，请缩小范围')
        model = dict(schemaVersion=1, type=kind, title=text(value.get('title'), '图名'),
                     purpose=text(value.get('purpose'), '用途', 1000), explanation=text(value.get('explanation', ''), '图说明', 16000, True),
                     nodes=[], edges=[], snapshotId=snapshot_id, runId=run_id)
        by_id = {}
        for node in nodes:
            if not isinstance(node, dict) or set(node) - {'id', 'label', 'role', 'evidenceIds', 'explanation', 'members', 'parentId'}:
                raise ValueError('UML 节点字段无效')
            nid = text(node.get('id'), '节点 ID', 100)
            if nid in by_id or node.get('role') not in ROLES[kind]:
                raise ValueError('节点 ID 重复或图形角色不符合 UML 类型')
            refs = citations(node.get('evidenceIds', []), node['role'] in DECORATIVE)
            members = node.get('members', [])
            if not isinstance(members, list) or len(members) > 100:
                raise ValueError('类成员数量无效')
            clean = dict(id=nid, label=text(node.get('label', ''), '节点名称', 300, node['role'] in DECORATIVE), role=node['role'],
                         evidence=refs, basis='inferred', explanation=text(node.get('explanation', ''), '节点解释', 8000, node['role'] in DECORATIVE),
                         members=[text(m, '成员', 300) for m in members])
            if node.get('parentId'):
                clean['parentId'] = text(node['parentId'], '分组 ID', 100)
            model['nodes'].append(clean)
            by_id[nid] = clean
        for node in model['nodes']:
            seen, parent = {node['id']}, node.get('parentId')
            while parent:
                if parent not in by_id or parent in seen:
                    raise ValueError('容器分组不存在或形成循环')
                seen.add(parent)
                parent = by_id[parent].get('parentId')
        containers = {'class': {'package'}, 'component': {'package','component'}, 'deployment': {'device','execution'}, 'usecase': {'system'}}
        for node in model['nodes']:
            if node.get('parentId') and by_id[node['parentId']]['role'] not in containers.get(kind, set()):
                raise ValueError('此 UML 类型或节点角色不支持容器分组')
        edge_ids, orders = set(), set()
        for index, relation in enumerate(edges):
            if not isinstance(relation, dict) or set(relation) - {'id', 'source', 'target', 'role', 'label', 'guard', 'evidenceIds', 'explanation', 'order'}:
                raise ValueError('UML 关系字段无效')
            eid = text(relation.get('id'), '关系 ID', 100)
            if eid in edge_ids or eid in by_id or relation.get('source') not in by_id or relation.get('target') not in by_id or relation.get('role', 'flow') not in EDGE_TYPES[kind]:
                raise ValueError('关系 ID、端点或类型无效')
            edge_ids.add(eid)
            source, dest = by_id[relation['source']], by_id[relation['target']]
            optional = source['role'] in DECORATIVE or dest['role'] in DECORATIVE
            ids = relation.get('evidenceIds', [])
            refs = citations(ids, optional)
            order = relation.get('order', index)
            if type(order) is not int or not 0 <= order <= 10000:
                raise ValueError('消息顺序无效')
            if kind == 'sequence' and order in orders:
                raise ValueError('时序消息的 order 必须唯一')
            orders.add(order)
            clean = dict(id=eid, source=source['id'], target=dest['id'], role=relation.get('role', 'flow'),
                         label=text(relation.get('label', ''), '连线名称', 300, True), guard=text(relation.get('guard', ''), '分支条件', 300, True),
                         explanation=text(relation.get('explanation', ''), '关系解释', 8000, optional), evidence=refs, basis='inferred', status='inferred', order=order)
            # A relation may be called an analyzer fact only if both semantic
            # endpoints cite its canonical endpoints. Otherwise it is inference.
            for ref in ids:
                fact = facts[ref]
                if fact.get('source') in {r['id'] for r in source['evidence']} and fact.get('target') in {r['id'] for r in dest['evidence']}:
                    clean.update(basis='analyzer', status=fact.get('status', 'resolved'), factKind=fact['kind'])
                    break
            if any(r['status'] in ('candidate', 'unresolved') for r in refs):
                clean['status'] = 'unresolved' if any(r['status'] == 'unresolved' for r in refs) else 'candidate'
            model['edges'].append(clean)
        all_refs = [r for n in model['nodes'] + model['edges'] for r in n['evidence']]
        if not all_refs:
            raise ValueError('图必须有可追溯的源码依据')
        model['evidence'] = list({(r['id'], r['path'], r['startLine']): r for r in all_refs}.values())
        for item in model['nodes'] + model['edges']:
            if not item['evidence']:
                item['evidence'] = model['evidence']
        results.append(dict(id=identifier or uuid.uuid4().hex, expectedRevision=expected, model=model))
    if require_target and target and not any(x['id'] == target['id'] for x in results):
        raise ValueError('本轮要求更新指定图，提交内容没有包含该图')
    return results


class DiagramStore:
    def _initialize_diagrams(self):
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS diagrams(id TEXT PRIMARY KEY, project TEXT NOT NULL,
                    current_revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    origin_conversation TEXT, legacy_conversation TEXT UNIQUE);
                CREATE INDEX IF NOT EXISTS project_diagrams ON diagrams(project,updated_at);
                CREATE TABLE IF NOT EXISTS diagram_versions(diagram_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    snapshot_id TEXT NOT NULL, conversation_id TEXT, run_id TEXT, created_at TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(diagram_id,revision));
                CREATE TABLE IF NOT EXISTS diagram_drafts(run_id TEXT PRIMARY KEY, project TEXT NOT NULL,
                    created_at TEXT NOT NULL, payload TEXT NOT NULL);
            ''')
            for conv in db.execute('SELECT * FROM conversations WHERE view_json IS NOT NULL').fetchall():
                self._import_legacy(db, dict(conv))

    def _import_legacy(self, db, conv):
        view = json.loads(conv['view_json'])
        if not view:
            return
        identifier = uuid.uuid5(uuid.NAMESPACE_URL, 'strata-legacy:' + conv['id']).hex
        old = db.execute('SELECT current_revision FROM diagrams WHERE id=?', (identifier,)).fetchone()
        if old:
            payload = json.loads(db.execute('SELECT payload FROM diagram_versions WHERE diagram_id=? AND revision=?', (identifier, old[0])).fetchone()[0])
            if payload.get('runId') == view.get('runId'):
                return
        model = dict(schemaVersion=1, type='legacy', title=view['title'], purpose=view.get('explanation') or '旧版阅读图，保留原始关系及源码快照。',
                     explanation=view.get('explanation', ''), snapshotId=view['snapshotId'], runId=view['runId'], legacy=view, nodes=[], edges=[], evidence=[])
        for item in view.get('nodes', []) + view.get('relations', []):
            if item.get('path') and item.get('range'):
                model['evidence'].append(dict(id=item['id'], snapshotId=view['snapshotId'], path=item['path'], range=item['range'],
                    startLine=item['range']['start'][0], endLine=item['range'].get('end', item['range']['start'])[0], locationKind='source', status=item.get('status', 'resolved')))
        revision, created = (old[0] + 1 if old else 1), stamp()
        if not old:
            db.execute('INSERT INTO diagrams VALUES(?,?,?,?,?,?,?)', (identifier, conv['project'], revision, created, created, conv['id'], conv['id']))
        else:
            db.execute('UPDATE diagrams SET current_revision=?,updated_at=? WHERE id=?', (revision, created, identifier))
        db.execute('INSERT INTO diagram_versions VALUES(?,?,?,?,?,?,?)', (identifier, revision, view['snapshotId'], conv['id'], view['runId'], created, dumps(model)))

    def diagram(self, project, identifier, revision=None):
        if not isinstance(identifier, str) or not re.fullmatch('[a-f0-9]{32}', identifier):
            raise ValueError('图 ID 无效')
        if revision is not None and (type(revision) is not int or revision < 1):
            raise ValueError('版本号无效')
        with self.connect() as db:
            row = db.execute('SELECT * FROM diagrams WHERE id=? AND project=?', (identifier, project)).fetchone()
            if not row:
                raise LookupError('图不存在或不属于当前项目')
            result = dict(row)
            version = db.execute('SELECT * FROM diagram_versions WHERE diagram_id=? AND revision=?', (identifier, revision or row['current_revision'])).fetchone()
            if not version:
                raise LookupError('图版本不存在')
            result.update(revision=version['revision'], model=json.loads(version['payload']), snapshotId=version['snapshot_id'], conversationId=version['conversation_id'])
            return result

    def list_diagrams(self, project, offset=0, limit=50):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('图列表分页参数无效')
        with self.connect() as db:
            rows = db.execute('SELECT d.*,v.payload FROM diagrams d JOIN diagram_versions v ON v.diagram_id=d.id AND v.revision=d.current_revision WHERE d.project=? ORDER BY d.updated_at,d.id LIMIT ? OFFSET ?', (project, limit + 1, offset)).fetchall()
        items = []
        for row in rows[:limit]:
            model = json.loads(row['payload'])
            items.append(dict(id=row['id'], revision=row['current_revision'], title=model['title'], type=model['type'], purpose=model['purpose'],
                snapshotId=model['snapshotId'], updatedAt=row['updated_at'], originConversation=row['origin_conversation'], runId=model.get('runId')))
        return dict(diagrams=items, nextOffset=offset + limit if len(rows) > limit else None)

    def diagram_versions(self, project, identifier):
        self.diagram(project, identifier)
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT revision,snapshot_id AS snapshotId,created_at AS createdAt,conversation_id AS conversationId FROM diagram_versions WHERE diagram_id=? ORDER BY revision DESC', (identifier,))]

    def save_diagram_draft(self, run_id, project, values):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO diagram_drafts VALUES(?,?,?,?)', (run_id, project, stamp(), dumps(values)))

    def diagram_drafts(self, project):
        with self.connect() as db:
            return [dict(runId=r['run_id'], createdAt=r['created_at'], diagrams=json.loads(r['payload'])) for r in db.execute('SELECT d.* FROM diagram_drafts d JOIN runs r ON r.id=d.run_id WHERE d.project=? AND r.status != ? ORDER BY d.created_at DESC LIMIT 30', (project, 'running'))]

    def _commit_diagrams(self, db, run, values):
        project = db.execute('SELECT project FROM conversations WHERE id=?', (run['conversation_id'],)).fetchone()[0]
        # Validate every expected revision before changing ANY document.
        for value in values:
            row = db.execute('SELECT project,current_revision FROM diagrams WHERE id=?', (value['id'],)).fetchone()
            if value['expectedRevision'] is not None:
                if not row or row['project'] != project or row['current_revision'] != value['expectedRevision']:
                    raise DiagramConflict('图已被另一会话更新；草稿已保留，请重新读取最新图后重试')
            elif row:
                raise DiagramConflict('新图 ID 冲突；草稿已保留')
        for value in values:
            revision, created = (value['expectedRevision'] or 0) + 1, stamp()
            if revision == 1:
                db.execute('INSERT INTO diagrams VALUES(?,?,?,?,?,?,NULL)', (value['id'], project, revision, created, created, run['conversation_id']))
            else:
                db.execute('UPDATE diagrams SET current_revision=?,updated_at=? WHERE id=?', (revision, created, value['id']))
            db.execute('INSERT INTO diagram_versions VALUES(?,?,?,?,?,?,?)', (value['id'], revision, value['model']['snapshotId'], run['conversation_id'], run['id'], created, dumps(value['model'])))
        db.execute('DELETE FROM diagram_drafts WHERE run_id=?', (run['id'],))

    def diagram_draft(self, project, run_id):
        with self.connect() as db:
            row = db.execute('SELECT payload FROM diagram_drafts WHERE project=? AND run_id=?', (project,run_id)).fetchone()
            if not row:
                raise LookupError('项目中没有此任务的草稿')
            return dict(runId=run_id, diagrams=json.loads(row['payload']))

    def diagram_source(self, project, identifier, revision, path, start=1, end=None):
        diagram = self.diagram(project, identifier, revision)
        # Directory browsing can read another captured file, but cannot escape
        # the authorized document's immutable snapshot.
        snapshot_file(self, diagram['snapshotId'], path)
        return self.source(diagram['snapshotId'], path, start, end)

    def check_diagram(self, project, identifier, revision=None, file_cache=None):
        diagram = self.diagram(project, identifier, revision)
        root, statuses, file_cache = Path(project).resolve(), [], file_cache if file_cache is not None else {}
        refs = {r['path']: r for r in diagram['model']['evidence']}
        for path, ref in refs.items():
            try:
                old = snapshot_file(self, diagram['snapshotId'], path)
                if path not in file_cache:
                    target = root / path
                    if target.is_symlink() or not target.resolve().is_relative_to(root):
                        raise ValueError('关联路径已成为符号链接或超出项目')
                    file_cache[path] = hashlib.sha256(target.read_text(encoding='utf-8').encode()).hexdigest()
                state = 'current' if file_cache[path] == old['contentHash'] else 'modified'
                statuses.append(dict(path=path, status=state))
            except FileNotFoundError:
                statuses.append(dict(path=path, status='deleted'))
            except (OSError, UnicodeError, ValueError, LookupError) as exc:
                statuses.append(dict(path=path, status='error', message=str(exc)[:300]))
        from .snapshots import fingerprint
        analyzer_changed = fingerprint(self.snapshot(diagram['snapshotId'])['data']) != diagram['snapshotId']
        return dict(id=identifier, revision=diagram['revision'], status='stale' if any(s['status'] in ('modified', 'deleted') for s in statuses) else 'error' if any(s['status'] == 'error' for s in statuses) else 'current',
                    files=statuses, analyzerChanged=analyzer_changed, checkedAt=stamp())
