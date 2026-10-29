"""Application-owned history. Each operation uses its own SQLite transaction."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid

from .diagrams import DiagramStore


def now():
    return datetime.now(timezone.utc).isoformat()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def default_database():
    root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share").expanduser()
    if not root.is_absolute():
        root = Path.home() / ".local/share"
    return root / "code-strata" / "exploration.sqlite3"


class Store(DiagramStore):
    def __init__(self, path=None, readonly=False):
        self.path = Path(path or default_database()).expanduser().resolve()
        self.readonly = readonly
        if readonly:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        os.chmod(self.path, 0o600)
        self._initialize()
        self._initialize_diagrams()

    def acquire_owner(self):
        """Only one app service may recover/write runs; history readers stay independent."""
        handle = self.path.with_suffix(self.path.suffix + '.lock').open('a+b')
        os.chmod(handle.name, 0o600)
        try:
            if os.name == 'nt':
                import msvcrt
                if handle.tell() == 0:
                    handle.write(b'0'); handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise ValueError('另一个看板正在使用此历史库；请复用该服务，或用 --history-db 指定独立历史库') from exc
        return handle

    def _initialize(self):
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS blobs(hash TEXT PRIMARY KEY, content TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY, project TEXT NOT NULL,
                    created_at TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY, project TEXT NOT NULL,
                    agent_id TEXT NOT NULL, title TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, snapshot_id TEXT, view_json TEXT, native_session_id TEXT);
                CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
                    status TEXT NOT NULL, snapshot_id TEXT, created_at TEXT NOT NULL,
                    finished_at TEXT, error TEXT, native_session_id TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS one_active_run ON runs(conversation_id)
                    WHERE status='running';
                CREATE TABLE IF NOT EXISTS messages(seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL, run_id TEXT, role TEXT NOT NULL,
                    kind TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS conversation_messages ON messages(conversation_id,seq);
                CREATE TABLE IF NOT EXISTS evidence(run_id TEXT NOT NULL, kind TEXT NOT NULL,
                    id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(run_id,kind,id));
            """)
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        if self.readonly:
            try:
                db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=10)
            except sqlite3.OperationalError as exc:
                raise ValueError('无法读取历史数据库，请检查 --database 路径并先在应用中创建会话') from exc
        else:
            db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def recover(self):
        with self.connect() as db:
            for row in db.execute("SELECT id,conversation_id FROM runs WHERE status='running'").fetchall():
                db.execute("UPDATE runs SET status='interrupted',finished_at=?,error=? WHERE id=?",
                           (now(), "服务已重启，可重新发送；原图已保留", row['id']))
                self._message(db, row['conversation_id'], row['id'], 'system', 'status',
                              {"status": "interrupted", "text": "服务已重启，任务中断；原图已保留"})

    def create(self, project, agent_id, title):
        identifier, stamp = uuid.uuid4().hex, now()
        with self.connect() as db:
            db.execute("INSERT INTO conversations(id,project,agent_id,title,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                       (identifier, project, agent_id, title, stamp, stamp))
        return self.conversation(identifier)

    def list(self, project):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT id,title,agent_id,created_at,updated_at,snapshot_id FROM conversations WHERE project=? ORDER BY updated_at DESC", (project,))]

    def conversation(self, identifier):
        if not isinstance(identifier, str) or len(identifier) != 32:
            raise ValueError("会话 ID 无效")
        with self.connect() as db:
            row = db.execute("SELECT * FROM conversations WHERE id=?", (identifier,)).fetchone()
            if row is None:
                raise LookupError("会话不存在")
            result = dict(row)
            result['view'] = json.loads(result.pop('view_json') or 'null')
            active = db.execute("SELECT * FROM runs WHERE conversation_id=? ORDER BY created_at DESC LIMIT 1", (identifier,)).fetchone()
            result['run'] = dict(active) if active else None
            return result

    def history(self, identifier, cursor=0, limit=100):
        conv = self.conversation(identifier)
        if type(cursor) is not int or cursor < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("历史分页参数无效")
        with self.connect() as db:
            rows = db.execute("SELECT m.*,r.snapshot_id FROM messages m LEFT JOIN runs r ON r.id=m.run_id WHERE m.conversation_id=? AND m.seq>? ORDER BY m.seq LIMIT ?",
                              (identifier, cursor, limit + 1)).fetchall()
        messages = [{**dict(r), "content": json.loads(r['content'])} for r in rows[:limit]]
        view = conv['view']
        return dict(id=identifier, agentId=conv['agent_id'], title=conv['title'], messages=messages,
                    nextCursor=messages[-1]['seq'] if len(rows) > limit else None,
                    viewSummary=None if not view else dict(title=view['title'], view=view['view'],
                        snapshotId=view['snapshotId'], nodes=len(view['nodes']), relations=len(view['relations'])))

    def _message(self, db, conversation_id, run_id, role, kind, content):
        db.execute("INSERT INTO messages(conversation_id,run_id,role,kind,content,created_at) VALUES(?,?,?,?,?,?)",
                   (conversation_id, run_id, role, kind, encoded(content), now()))

    def message(self, conversation_id, run_id, role, kind, content):
        with self.connect() as db:
            self._message(db, conversation_id, run_id, role, kind, content)

    def assistant(self, conversation_id, run_id, text):
        if len(text) > 131072:
            raise ValueError('Agent 本轮解释超过长度限制')
        with self.connect() as db:
            row = db.execute("SELECT seq FROM messages WHERE run_id=? AND role='assistant' AND kind='text' LIMIT 1", (run_id,)).fetchone()
            if row:
                db.execute('UPDATE messages SET content=? WHERE seq=?', (encoded({'text': text}), row['seq']))
            else:
                self._message(db, conversation_id, run_id, 'assistant', 'text', {'text': text})

    def start(self, identifier, text):
        self.conversation(identifier)
        run_id = uuid.uuid4().hex
        try:
            with self.connect() as db:
                db.execute("INSERT INTO runs(id,conversation_id,status,created_at) VALUES(?,?,'running',?)", (run_id, identifier, now()))
                self._message(db, identifier, run_id, 'user', 'text', {"text": text})
                db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now(), identifier))
        except sqlite3.IntegrityError as exc:
            raise ValueError("此会话已有任务正在执行") from exc
        return run_id

    def bind(self, run_id, snapshot_id):
        with self.connect() as db:
            db.execute("UPDATE runs SET snapshot_id=? WHERE id=? AND status='running'", (snapshot_id, run_id))

    def native_session(self, run_id, identifier):
        if not isinstance(identifier, str) or not identifier or len(identifier) > 512:
            return
        with self.connect() as db:
            db.execute("UPDATE runs SET native_session_id=? WHERE id=?", (identifier, run_id))
            db.execute("UPDATE conversations SET native_session_id=? WHERE id=(SELECT conversation_id FROM runs WHERE id=?)", (identifier, run_id))

    def finish(self, run_id, status, error=None, view=None, diagrams=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            run = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if not run or run['status'] != 'running':
                return
            if diagrams and status == 'completed':
                self._commit_diagrams(db, run, diagrams)
                db.execute('UPDATE conversations SET snapshot_id=?,updated_at=? WHERE id=?', (diagrams[-1]['model']['snapshotId'], now(), run['conversation_id']))
            if view is not None and status == 'completed':
                db.execute("UPDATE conversations SET view_json=?,snapshot_id=?,updated_at=? WHERE id=?",
                           (encoded(view), view['snapshotId'], now(), run['conversation_id']))
                self._import_legacy(db, dict(db.execute('SELECT * FROM conversations WHERE id=?', (run['conversation_id'],)).fetchone()))
            if diagrams and status == 'completed':
                self._message(db, run['conversation_id'], run_id, 'system', 'diagrams', {'diagramIds': [d['id'] for d in diagrams]})
            db.execute("UPDATE runs SET status=?,error=?,finished_at=? WHERE id=?", (status, error, now(), run_id))
            self._message(db, run['conversation_id'], run_id, 'system', 'status', {"status": status, "text": error or "本轮阅读完成"})

    def record_facts(self, run_id, result):
        with self.connect() as db:
            for kind, items in (('node', result.get('nodes', [])), ('relation', result.get('relations', []))):
                for item in items:
                    db.execute("INSERT OR REPLACE INTO evidence VALUES(?,?,?,?)", (run_id, kind, item['id'], encoded(item)))

    def facts(self, run_id, kind):
        with self.connect() as db:
            return {r['id']: json.loads(r['payload']) for r in db.execute("SELECT id,payload FROM evidence WHERE run_id=? AND kind=?", (run_id, kind))}

    def snapshot(self, identifier):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM snapshots WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise LookupError("源码快照不存在")
            payload = json.loads(row['payload'])
            def restore(items):
                for item in items:
                    blob = item.pop('contentHash', None)
                    if blob:
                        item['content'] = db.execute("SELECT content FROM blobs WHERE hash=?", (blob,)).fetchone()[0]
            restore(payload['data']['files'])
            restore(payload['context']['files'])
            restore(payload['context'].get('sourceFiles', []))
            for key, digest in list(payload['context']['configs'].items()):
                payload['context']['configs'][key] = db.execute("SELECT content FROM blobs WHERE hash=?", (digest,)).fetchone()[0]
            return payload

    def save_snapshot(self, identifier, project, data, context):
        payload = json.loads(encoded(dict(data=data, context=context)))
        with self.connect() as db:
            def capture(text):
                digest = hashlib.sha256(text.encode()).hexdigest()
                db.execute("INSERT OR IGNORE INTO blobs VALUES(?,?)", (digest, text))
                return digest
            for items in (payload['data']['files'], payload['context']['files'],
                          payload['context'].get('sourceFiles', [])):
                for item in items:
                    if isinstance(item.get('content'), str):
                        item['contentHash'] = capture(item.pop('content'))
            payload['context']['configs'] = {k: capture(v) for k, v in payload['context'].get('configs', {}).items()}
            db.execute("INSERT OR IGNORE INTO snapshots VALUES(?,?,?,?)", (identifier, project, now(), encoded(payload)))

    def source(self, snapshot_id, path, start=1, end=None):
        if not isinstance(path, str) or type(start) is not int or start < 1 or (end is not None and (type(end) is not int or end < start)):
            raise ValueError("源码范围无效")
        with self.connect() as db:
            row = db.execute('SELECT payload FROM snapshots WHERE id=?', (snapshot_id,)).fetchone()
            if not row:
                raise LookupError('源码快照不存在')
            payload = json.loads(row['payload'])
            context = payload['context']
            file = next((f for f in context['files'] + context.get('sourceFiles', []) if f['id'] == path), None)
            digest = file.get('contentHash') if file else context.get('configs', {}).get(path)
            if not digest:
                item = next((f for f in payload['data'].get('inventory', []) if f['id'] == path), None)
                if item and item.get('captureStatus') != 'captured':
                    raise LookupError('该文件未能进入源码快照：' + (item.get('captureReason') or '扫描期间文件变化或读取受限'))
                if item:
                    raise LookupError('此旧快照未保留该文件正文，请让 Agent 更新以创建新快照')
                raise LookupError('本轮源码快照中没有该文件，请检查路径；若文件是后来新增的，请让 Agent 更新')
            content = db.execute('SELECT content FROM blobs WHERE hash=?', (digest,)).fetchone()[0]
            language = file.get('language') if file else {
                '.json': 'json', '.toml': 'toml', '.txt': 'plaintext', '.lock': 'plaintext',
            }.get(Path(path).suffix.lower(), 'plaintext')
        lines = content.split('\n')
        if start > len(lines):
            raise ValueError('起始行超出快照文件范围')
        stop = min(end or start + 299, start + 299, len(lines))
        return dict(snapshotId=snapshot_id, path=path, language=language, startLine=start,
                    endLine=stop, totalLines=len(lines), content='\n'.join(lines[start-1:stop]),
                    nextLine=stop + 1 if stop < len(lines) else None)
