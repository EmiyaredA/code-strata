"""Reading captured text is independent of semantic parser coverage."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from exploration.snapshots import capture
from exploration.store import Store
from exploration.tools import read_tool
from inventory import verify_inputs


class SnapshotSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        (self.project / 'main.py').write_text('def entry():\n    return 1\n')
        (self.project / 'package.json').write_text('{"name":"original"}\n')
        (self.project / 'index.html').write_text('<html>\n<body>original</body>\n</html>\n')
        self.store = Store(self.root / 'history.sqlite3')

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        identifier, data, context = capture(self.project, scc='/missing-counter')
        self.store.save_snapshot(identifier, str(self.project), data, context)
        return identifier, data, context

    def test_config_and_html_survive_restart_and_live_changes_without_semantic_claims(self):
        snapshot, data, context = self.save()
        self.assertEqual([f['id'] for f in context['files']], ['main.py'])
        html = next(f for f in data['inventory'] if f['id'] == 'index.html')
        self.assertEqual(html['parseStatus'], 'unsupported')
        conv = self.store.create(str(self.project), 'codex', 'read entry')
        run = self.store.start(conv['id'], 'read source')
        self.store.bind(run, snapshot)
        (self.project / 'package.json').write_text('{"name":"changed"}')
        (self.project / 'index.html').unlink()
        reader = Store(self.store.path, readonly=True)
        for path, language in [('package.json', 'json'), ('index.html', 'html')]:
            source = read_tool(reader, 'read_snapshot_source', dict(id=conv['id'], snapshotId=snapshot, path=path))
            self.assertIn('original', source['content'])
            self.assertEqual(source['language'], language)
        page = reader.source(snapshot, 'index.html', 2, 2)
        self.assertEqual((page['content'], page['nextLine']), ('<body>original</body>', 3))
        restored = reader.snapshot(snapshot)
        self.assertIn('original', restored['context']['sourceFiles'][0]['content'])
        # A legacy snapshot already contains configuration blobs, but not HTML.
        with self.store.connect() as db:
            payload = json.loads(db.execute('SELECT payload FROM snapshots WHERE id=?', (snapshot,)).fetchone()[0])
            payload['context'].pop('sourceFiles')
            db.execute('UPDATE snapshots SET payload=? WHERE id=?', (json.dumps(payload), snapshot))
        self.assertIn('original', reader.source(snapshot, 'package.json')['content'])
        with self.assertRaisesRegex(LookupError, '旧快照.*更新'):
            reader.source(snapshot, 'index.html')

    def test_full_file_can_be_reassembled_from_bounded_historical_chunks(self):
        text = '\n'.join(f'# immutable line {n}' for n in range(1, 995))
        path = self.project / 'long.py'
        path.write_text(text)
        snapshot, _, _ = self.save()
        path.unlink()
        reader = Store(self.store.path)
        pieces = []
        for start in (1, 301, 601, 901):
            block = reader.source(snapshot, 'long.py', start, 100000)
            self.assertEqual(block['startLine'], start)
            self.assertLessEqual(block['endLine'] - start + 1, 300)
            self.assertEqual(block['totalLines'], 994)
            pieces.append(block['content'])
        self.assertEqual('\n'.join(pieces), text)
        self.assertIsNone(block['nextLine'])

    def test_parser_budget_does_not_prevent_snapshot_reading(self):
        text = '# large source\n' + ' ' * (512 * 1024)
        (self.project / 'large.py').write_text(text)
        snapshot, data, _ = self.save()
        item = next(f for f in data['inventory'] if f['id'] == 'large.py')
        self.assertEqual(item['parseStatus'], 'skipped')
        self.assertEqual(self.store.source(snapshot, 'large.py', 1, 1)['content'], '# large source')

    def test_changed_and_excluded_inputs_are_never_read_from_live_disk(self):
        (self.project / '.env').write_text('SECRET=excluded')
        def mutate(root, entries, originals):
            (root / 'index.html').write_text('changed during scan')
            return verify_inputs(root, entries, originals)
        with patch('scan.verify_inputs', side_effect=mutate):
            snapshot, _, context = self.save()
        self.assertEqual(context['sourceFiles'], [])
        with self.assertRaisesRegex(LookupError, '扫描期间文件变化'):
            self.store.source(snapshot, 'index.html')
        for path in ('.env', '../project/main.py', 'missing.py'):
            with self.assertRaisesRegex(LookupError, '本轮源码快照中没有'):
                self.store.source(snapshot, path)


if __name__ == '__main__':
    unittest.main()
