import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from agents.config import SettingsStore, defaults
from exploration.store import Store
from exploration.tools import read_tool, validate_view
from serve import make_server


class ExplorationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='strata reading ', dir=os.environ.get('CODE_ARCHITECTURE_TEST_TMP'))
        self.root = Path(self.temp.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        (self.project / 'main.py').write_text('def validate(value):\n    return bool(value)\n\ndef complete(value):\n    return validate(value)\n')
        self.cli = self.root / 'fake agent'
        self.cli.write_text(f'#!{sys.executable}\n' + (ROOT / 'tests/fixtures/exploration_cli.py').read_text())
        self.cli.chmod(0o700)
        self.settings = self.root / 'settings.json'
        config = defaults()
        config['agents'] = {key: dict(executablePath=str(self.cli), model='') for key in config['agents']}
        SettingsStore(self.settings).save(config)
        self.env = patch.dict(os.environ, {'STRATA_EXPLORATION_MCP': str(ROOT / 'scripts/exploration_mcp.py')})
        self.env.start()
        self.open_server()

    def open_server(self):
        self.server = make_server(self.project, settings_path=self.settings, exploration_timeout=15)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        with urlopen(self.url) as response:
            self.token = re.search('architecture-token" content="([^"]+)', response.read().decode())[1]

    def close_server(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def tearDown(self):
        self.close_server()
        self.env.stop()
        self.temp.cleanup()

    def api(self, path, body=None, token=None):
        headers = {'X-Architecture-Token': self.token if token is None else token}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        request = Request(self.url + path, data=None if body is None else json.dumps(body).encode(), headers=headers)
        with urlopen(request, timeout=20) as response:
            return json.load(response)

    def create(self, agent='codex'):
        return self.api('/api/explore/conversations', dict(agentId=agent, title='阅读 complete'))['id']

    def wait(self, identifier):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            conv = self.api('/api/explore/conversations/' + identifier)
            if conv['run'] and conv['run']['status'] != 'running':
                return conv
            time.sleep(.03)
        self.fail('reading run did not settle')

    def run_agent(self, identifier, update=False, mode='success'):
        with patch.dict(os.environ, {'STRATA_EXPLORATION_FIXTURE': mode}):
            self.api(f'/api/explore/conversations/{identifier}/messages', dict(text='请画出 complete 的调用关系', update=update))
            return self.wait(identifier)

    def test_all_five_native_transports_use_mcp_and_continue(self):
        for agent in ('codex', 'opencode', 'dsh', 'claude', 'pi'):
            with self.subTest(agent=agent):
                identifier = self.create(agent)
                first = self.run_agent(identifier)
                self.assertEqual(first['run']['status'], 'completed', first['run'])
                self.assertTrue(first['native_session_id'])
                self.assertTrue(first['view']['relations'])
                self.assertEqual(first['view']['snapshotId'], first['snapshot_id'])
                self.assertTrue(any(m['kind'] == 'tool_call' for m in first['history']['messages']))
                second = self.run_agent(identifier)
                self.assertEqual(second['run']['status'], 'completed', second['run'])
                self.assertEqual(first['snapshot_id'], second['snapshot_id'])
                self.assertEqual(second['agent_id'], agent)

    def test_module_handoff_resolves_complete_scope_from_the_run_snapshot(self):
        identifier = self.create()
        conv = self.run_agent(identifier)
        service = self.server.exploration
        snapshot = service.store.snapshot(conv['snapshot_id'])
        group = snapshot['data']['groups'][0]
        marker = '\n\n已选代码范围（定位线索，请在本轮源码快照中重新查询，不沿用旧节点 ID 或行号；模块文件列表最多展示前 30 项）：\n'
        text = '解释模块' + marker + json.dumps(dict(kind='group', groupId=group['id'], snapshotId='old', files=[]))
        prompt = service._prompt(conv, text, conv['snapshot_id'], False)
        line = next(line for line in prompt.splitlines() if line.startswith('本轮快照中的完整模块范围'))
        scope = json.loads(line.split('：', 1)[1])
        self.assertEqual(scope['files'], group['files'])
        self.assertIn('调用关系仍须使用工具查证', line)
        missing = service._prompt(conv, '解释模块' + marker + json.dumps(dict(kind='group', groupId='missing')), conv['snapshot_id'], False)
        self.assertIn('所选旧模块在本轮快照中已不存在', missing)
        # Ordinary questions and malformed optional metadata still work.
        for question in ('普通问题', '问题' + marker + '{', '问题' + marker + '[]'):
            self.assertIn('用户当前问题：' + question, service._prompt(conv, question, conv['snapshot_id'], False))

    def test_restart_pagination_external_reads_and_original_sources(self):
        identifier = self.create()
        original = self.run_agent(identifier)
        snapshot = original['snapshot_id']
        self.close_server(); self.open_server()
        restored = self.api('/api/explore/conversations/' + identifier)
        self.assertEqual(restored['view'], original['view'])
        store = Store(self.root / 'exploration.sqlite3', readonly=True)
        page = read_tool(store, 'get_conversation', dict(id=identifier, limit=2))
        self.assertEqual(len(page['messages']), 2)
        next_page = read_tool(store, 'get_conversation', dict(id=identifier, cursor=page['nextCursor'], limit=2))
        self.assertGreater(next_page['messages'][0]['seq'], page['messages'][-1]['seq'])
        (self.project / 'main.py').write_text('changed live source\n')
        source = read_tool(store, 'read_snapshot_source', dict(id=identifier, snapshotId=snapshot, path='main.py'))
        self.assertIn('def complete', source['content'])
        command = [sys.executable, str(ROOT / 'scripts/exploration_mcp.py'), '--database', str(store.path), '--call', 'get_view', '--arguments', json.dumps(dict(id=identifier))]
        external = subprocess.run(command, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(external.stdout)['view'], original['view'])
        with self.assertRaises(ValueError):
            read_tool(store, 'save_view', dict(id=identifier))
        with store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM blobs').fetchone()[0], 1)

    def test_stale_add_modify_delete_and_explicit_update(self):
        identifier = self.create()
        original = self.run_agent(identifier)
        for operation in ('add', 'modify', 'delete'):
            if operation == 'add':
                (self.project / 'caller.py').write_text('from main import complete\ncomplete(1)\n')
            elif operation == 'modify':
                (self.project / 'main.py').write_text((self.project / 'main.py').read_text() + '\n# updated\n')
            else:
                (self.project / 'caller.py').unlink()
            self.api(f'/api/explore/conversations/{identifier}/check', {})
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                conv = self.api('/api/explore/conversations/' + identifier)
                if conv['freshness']['status'] != 'checking':
                    break
                time.sleep(.03)
            self.assertEqual(conv['freshness']['status'], 'stale', conv['freshness'])
        followup = self.run_agent(identifier)
        self.assertEqual(followup['snapshot_id'], original['snapshot_id'])
        updated = self.run_agent(identifier, update=True)
        self.assertEqual(updated['run']['status'], 'completed')
        self.assertNotEqual(updated['snapshot_id'], original['snapshot_id'])
        with self.server.exploration.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM snapshots').fetchone()[0], 2)

    def test_invalid_evidence_failed_update_and_cancel_preserve_old_graph(self):
        identifier = self.create()
        original = self.run_agent(identifier)
        for mode in ('invalid', 'failure'):
            result = self.run_agent(identifier, update=True, mode=mode)
            self.assertEqual(result['run']['status'], 'failed')
            self.assertEqual(result['view'], original['view'])
        with patch.dict(os.environ, {'STRATA_EXPLORATION_FIXTURE': 'hold'}):
            self.api(f'/api/explore/conversations/{identifier}/messages', dict(text='请更新图', update=True))
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                job = next(j for j in self.server.exploration.jobs.values() if not j['done'].is_set())
                if job['pending']:
                    break
                time.sleep(.03)
            with self.assertRaises(HTTPError) as conflict:
                self.api(f'/api/explore/conversations/{identifier}/messages', dict(text='并发问题'))
            self.assertEqual(conflict.exception.code, 409); conflict.exception.close()
            self.api(f'/api/explore/conversations/{identifier}/cancel', {})
            result = self.wait(identifier)
        self.assertEqual(result['run']['status'], 'cancelled')
        self.assertEqual(result['view'], original['view'])
        with self.assertRaises(PermissionError):
            self.server.exploration.tool(job['id'], 'old-token', 'search_code', dict(text='complete'))

    def test_canonical_status_and_snapshot_scoped_evidence(self):
        identifier = self.create()
        result = self.run_agent(identifier)
        store, run_id, snapshot = self.server.exploration.store, result['run']['id'], result['snapshot_id']
        args = dict(title='test', view='functions', nodes=[n['id'] for n in result['view']['nodes']], relations=[r['id'] for r in result['view']['relations']])
        fact = copy.deepcopy(result['view']['relations'][0]); fact['status'] = 'candidate'
        store.record_facts(run_id, dict(relations=[fact]))
        validated = validate_view(store, run_id, snapshot, args)
        self.assertEqual(validated['relations'][0]['status'], 'candidate')
        other_run = store.start(identifier, 'new run')
        with self.assertRaises(ValueError):
            validate_view(store, other_run, snapshot, args)
        store.finish(other_run, 'cancelled')
        with self.assertRaises(ValueError):
            validate_view(store, run_id, snapshot, dict(args, nodes=[args['nodes'][0]]))
        second = self.create()
        with self.assertRaises(ValueError):
            read_tool(store, 'read_snapshot_source', dict(id=second, snapshotId=snapshot, path='main.py'))

    def test_http_auth_and_fixed_agent(self):
        with self.assertRaises(HTTPError) as denied:
            self.api('/api/explore/conversations', token='wrong')
        self.assertEqual(denied.exception.code, 403); denied.exception.close()
        identifier = self.create()
        with self.assertRaises(HTTPError) as denied:
            self.api(f'/api/explore/conversations/{identifier}/messages', dict(text='question', agentId='pi'))
        self.assertEqual(denied.exception.code, 422); denied.exception.close()
        self.server.exploration.store.start(identifier, 'interrupted work')
        self.close_server(); self.open_server()
        restored = self.api('/api/explore/conversations/' + identifier)
        self.assertEqual(restored['run']['status'], 'interrupted')

    def test_ts_unresolved_calls_and_analyzer_change_remain_explicit(self):
        (self.project / 'feature.ts').write_text('function validate(v: string) { return !!v; }\nexport function complete(v: string, handler: () => void) { handler(); return validate(v); }\n')
        identifier = self.create()
        with patch.dict(os.environ, {'STRATA_EXPLORATION_TS': '1'}):
            result = self.run_agent(identifier)
        self.assertEqual(result['run']['status'], 'completed', result['run'])
        self.assertTrue(any(r['kind'] == 'unresolved-call' and r['status'] == 'unresolved' for r in result['view']['relations']))
        self.assertTrue(any(r['kind'] == 'calls' for r in result['view']['relations']))
        self.assertTrue(all(n['path'] == 'feature.ts' for n in result['view']['nodes']))
        with patch('exploration.service.capture', return_value=('new-analyzer', dict(snapshot=dict(id='new-analyzer')), {})):
            self.api(f'/api/explore/conversations/{identifier}/check', {})
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                conv = self.api('/api/explore/conversations/' + identifier)
                if conv['freshness']['status'] != 'checking': break
                time.sleep(.03)
        self.assertEqual(conv['freshness']['status'], 'stale')

    def test_history_reader_survives_exclusive_service_owner(self):
        identifier = self.create()
        store = self.server.exploration.store
        with self.assertRaises(ValueError):
            store.acquire_owner()
        reader = Store(store.path, readonly=True)
        self.assertEqual(read_tool(reader, 'get_conversation', dict(id=identifier))['id'], identifier)
        with self.assertRaises(ValueError):
            read_tool(Store(self.root / 'missing.sqlite3', readonly=True), 'get_view', dict(id=identifier))


if __name__ == '__main__':
    unittest.main()
