from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from code_analysis.service import CodeSession


class CallHierarchyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        content = '''def leaf():
    return 1
class Box:
    def __init__(self):
        leaf()
    def work(self):
        return 1
    def candidate(self):
        self.work()
def root(handler):
    Box()
    leaf()
    leaf()
    handler()
    recursive()
def recursive():
    return recursive()
root(None)
'''
        content += '\n'.join(f'def f{i}(): return {i}' for i in range(120))
        content += '\ndef many():\n' + ''.join(f'    f{i}()\n' for i in range(120))
        content += '\ndef many_sites():\n' + '    leaf()\n' * 120
        file = dict(id='sample.py', content=content, language='python', captureStatus='captured', parseStatus='parsed')
        cls.session = CodeSession(dict(files=[file], snapshot=dict(id='hierarchy-test')), dict(files=[file]))
        cls.session.build()
        cls.nodes = cls.session.by_id.values()

    def node(self, name, kind='function'):
        return next(n for n in self.nodes if n['name'] == name and n['kind'] == kind)

    def query(self, name, direction='outgoing', **kwargs):
        return self.session.query(dict(view='hierarchy', focusId=self.node(name)['id'], direction=direction, **kwargs))

    def test_one_hop_direction_and_multi_sites_are_source_backed(self):
        result = self.query('root')
        names = {n['name'] for n in result['nodes']}
        self.assertIn('__init__', names)
        self.assertNotIn('work', names)
        leaf = self.node('leaf')
        relation = next(r for r in result['relations'] if r['target'] == leaf['id'])
        self.assertEqual(relation['siteCount'], 2)
        self.assertEqual([s['range']['start'][0] for s in relation['sites']], [12, 13])
        incoming = self.query('leaf', 'incoming')
        self.assertEqual({n['name'] for n in incoming['nodes']}, {'leaf', 'root', '__init__', 'many_sites'})
        self.assertTrue(all(r['target'] == leaf['id'] for r in incoming['relations']))

    def test_constructor_candidate_and_unknown_remain_distinct(self):
        result = self.query('root')
        ctor = next(n for n in result['nodes'] if n['kind'] == 'constructor')
        self.assertEqual(ctor['qualifiedName'], 'Box.__init__')
        unknown = next(n for n in result['nodes'] if n['kind'] == 'call')
        self.assertEqual(unknown['name'], 'handler')
        self.assertEqual(unknown['status'], 'unresolved')
        self.assertTrue(any(r['kind'] == 'unresolved-call' and r['range']['start'][0] == 14 for r in result['relations']))
        candidate = self.session.query(dict(view='hierarchy', focusId=self.node('candidate', 'method')['id']))
        self.assertEqual(candidate['relations'][0]['status'], 'candidate')

    def test_module_top_level_and_recursion_are_not_fake_functions(self):
        incoming = self.query('root', 'incoming')
        module = next(n for n in incoming['nodes'] if n['kind'] == 'file')
        self.assertTrue(module['moduleTopLevel'])
        self.assertEqual(incoming['relations'][0]['range']['start'][0], 18)
        module_calls = self.session.query(dict(view='hierarchy', focusId=module['id']))
        self.assertEqual({n['name'] for n in module_calls['nodes']}, {'sample.py', 'root'})
        recurse = self.query('recursive')
        self.assertEqual(len(recurse['nodes']), 1)
        self.assertEqual(recurse['relations'][0]['source'], recurse['relations'][0]['target'])

    def test_pages_keep_focus_and_all_direct_edges_without_dangling_ids(self):
        offset, seen = 0, set()
        while True:
            result = self.query('many', limit=17, offset=offset)
            self.assertLessEqual(len(result['nodes']), 17)
            ids = {n['id'] for n in result['nodes']}
            self.assertIn(self.node('many')['id'], ids)
            self.assertTrue(all(r['source'] in ids and r['target'] in ids for r in result['relations']))
            new = {r['id'] for r in result['relations']}
            self.assertFalse(new & seen)
            seen.update(new)
            if result['nextOffset'] is None:
                break
            self.assertGreater(result['nextOffset'], offset)
            offset = result['nextOffset']
        self.assertEqual(len(seen), 120)

    def test_invalid_direction_scope_and_budget_do_not_silently_query_another_view(self):
        for patch in [dict(direction='both'), dict(limit=1), dict(focusId='missing')]:
            with self.assertRaises(ValueError):
                self.session.query(dict(view='hierarchy', focusId=self.node('root')['id'], **patch) if 'focusId' not in patch else dict(view='hierarchy', **patch))
        leaf = self.query('leaf')
        self.assertEqual(leaf['relations'], [])

    def test_call_site_budget_reports_the_total_without_inventing_more_locations(self):
        result = self.query('many_sites')
        self.assertEqual(len(result['relations']), 1)
        self.assertEqual(result['relations'][0]['siteCount'], 120)
        self.assertEqual(len(result['relations'][0]['sites']), 100)
        self.assertTrue(result['siteTruncated'])


if __name__ == '__main__':
    unittest.main()
