import argparse
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
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from dev import ReloadControl, backend_command, revision, validate_python
from serve import make_server


class DevWatchTests(unittest.TestCase):
    def test_syntax_error_during_drain_keeps_old_backend_until_fixed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.py'
            source.write_text('def invalid(\n')
            request = root / 'reload'
            request.touch()
            server = Mock()
            server.reload_idle.return_value = True
            control = ReloadControl(server, request, root)
            control.thread.start()
            try:
                time.sleep(.3)
                server.begin_reload.assert_not_called()
                server.shutdown.assert_not_called()
                source.write_text('VALUE = 1\n')
                control.thread.join(timeout=3)
                self.assertTrue(control.ready)
                server.shutdown.assert_called_once_with()
            finally:
                control.close()

    def test_source_add_modify_delete_and_syntax_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = revision(root)
            path = root / 'new.py'
            path.write_text('value = 1\n')
            second = revision(root)
            self.assertNotEqual(first, second)
            validate_python(second)
            (root / 'history.sqlite3').write_text('not an input')
            self.assertEqual(second, revision(root))
            path.write_text('def invalid(\n')
            self.assertNotEqual(second, revision(root))
            with self.assertRaises(SyntaxError):
                validate_python(revision(root))
            path.unlink()
            self.assertEqual(first, revision(root))

    def test_relaunch_preserves_cli_settings_and_assigned_port(self):
        args = argparse.Namespace(project='/my project', mapping='/mapping.json', node='/node',
                                  scc=None, work_dir='/temporary', history_db='/history.sqlite3')
        command = backend_command(args, 54321)
        self.assertIn('-B', command)
        self.assertEqual(command[command.index('--port') + 1], '54321')
        for key in ('project', 'mapping', 'node', 'work_dir', 'history_db'):
            self.assertEqual(command[command.index('--' + key.replace('_', '-')) + 1], getattr(args, key))
        self.assertNotIn('--open', command)


class DevDrainTests(unittest.TestCase):
    def test_reload_waits_for_agent_and_allows_its_tool_requests_and_cancel(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / 'project'
            project.mkdir()
            (project / 'main.py').write_text('value = 1\n')
            server = make_server(project, settings_path=root / 'settings.json',
                                 dev=dict(token='test-token', frontend='http://127.0.0.1:1', save=lambda *_: None))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                # A live run keeps the old process and its capability alive.
                urlopen(Request(base + '/api/explore/conversations', headers={'X-Architecture-Token': 'test-token'})).close()
                done = threading.Event()
                server.exploration.jobs['live'] = dict(done=done, conversationId='unused', cancel=threading.Event())
                server.begin_reload()
                self.assertFalse(server.reload_idle())
                request = Request(base + '/api/explore/conversations', data=b'{}',
                                  headers={'X-Architecture-Token': 'test-token', 'Content-Type': 'application/json'})
                with self.assertRaises(HTTPError) as error:
                    urlopen(request)
                self.assertEqual(error.exception.code, 503)
                error.exception.close()
                # Tool capability validation still executes; the reload gate must
                # not reject the running Agent's tool request with 503.
                request = Request(base + '/api/explore/tools', data=b'{}', headers={'Content-Type': 'application/json'})
                with self.assertRaises(HTTPError) as error:
                    urlopen(request)
                self.assertEqual(error.exception.code, 403)
                error.exception.close()
                done.set()
                self.assertTrue(server.reload_idle())
                server.active_requests = 1
                self.assertFalse(server.reload_idle())
                server.active_requests = 0
            finally:
                if server.exploration:
                    server.exploration.jobs.clear()
                server.shutdown(); server.server_close(); thread.join()


@unittest.skipUnless((ROOT / 'assets/board-source/node_modules/vite/bin/vite.js').is_file(), 'Vite dependencies not installed')
class DevProcessTests(unittest.TestCase):
    def test_full_supervisor_keeps_origin_token_project_and_history_after_reload(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            watched = root / 'watched'
            watched.mkdir()
            source = watched / 'probe.py'
            source.write_text('VALUE = 1\n')
            for name in ('first', 'second'):
                project = root / name
                project.mkdir()
                (project / 'main.py').write_text('def entry():\n    return 1\n')
            args = dict(project=str(root / 'first'), mapping=None, node=None, scc='/missing-counter',
                        work_dir=None, history_db=str(root / 'history.sqlite3'), port=0, open=False)
            code = ('import sys, argparse; sys.path.insert(0, sys.argv[1]); from dev import run; '
                    'import json; raise SystemExit(run(argparse.Namespace(**json.loads(sys.argv[2])), watch_root=sys.argv[3]))')
            process = subprocess.Popen([sys.executable, '-B', '-u', '-c', code, str(ROOT / 'scripts'),
                                        json.dumps(args), str(watched)], stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True,
                                       env=dict(os.environ, XDG_CONFIG_HOME=str(root / 'config')))
            lines, metadata = [], []
            def collect():
                for line in process.stdout:
                    lines.append(line)
                    if line.startswith('{"url":'):
                        metadata.append(json.loads(line))
            reader = threading.Thread(target=collect, daemon=True)
            reader.start()
            def wait(predicate):
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline:
                    if predicate():
                        return
                    self.assertIsNone(process.poll(), ''.join(lines)[-2500:])
                    time.sleep(.05)
                self.fail('development service timed out: ' + ''.join(lines)[-2500:])
            try:
                wait(lambda: len(metadata) == 1)
                base = metadata[0]['url']
                with urlopen(base) as response:
                    html = response.read().decode()
                self.assertIn('/@vite/client', html)
                token = re.search('architecture-token" content="([^"]+)', html)[1]
                def api(path, body=None):
                    request = Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                      headers={'X-Architecture-Token': token, 'Content-Type': 'application/json'})
                    with urlopen(request, timeout=15) as response:
                        return json.load(response)
                # Same-origin proxy returns transformed JSX modules as well as HTML.
                with urlopen(base + '/src/App.jsx') as response:
                    self.assertIn('/@react-refresh', response.read().decode())
                api('/api/project', dict(path=str(root / 'second')))
                conv = api('/api/explore/conversations', dict(agentId='codex', title='keep this conversation'))
                source.write_text('def invalid(\n')
                wait(lambda: any('暂不重载' in line for line in lines))
                self.assertEqual(len(metadata), 1)
                self.assertEqual(api('/api/project')['project']['name'], 'second')
                source.write_text('VALUE = 2\n')
                wait(lambda: len(metadata) >= 2)
                self.assertEqual(metadata[-1]['url'], base)
                self.assertEqual(api('/api/project')['project']['name'], 'second')
                self.assertEqual(api('/api/explore/conversations')['conversations'][0]['id'], conv['id'])
                with urlopen(base) as response:
                    self.assertIn(f'content="{token}"', response.read().decode())
                source.unlink()
                wait(lambda: len(metadata) >= 3)
                self.assertEqual(api('/api/project')['project']['name'], 'second')
            finally:
                process.terminate()
                process.wait(timeout=20)
                reader.join(timeout=3)
                process.stdout.close()
