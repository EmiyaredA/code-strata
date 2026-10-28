import json
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from code_analysis.service import CodeSession, run_language
from code_analysis.python_engine import analyze
from code_analysis.model import FUNCTIONS
from scan import scan_project

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/code-browser'


class CodeAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = {}
        cls.data = scan_project(FIXTURE, node=os.environ.get('CODE_ARCHITECTURE_TEST_NODE'), snapshot_context=cls.context)
        cls.session = CodeSession(cls.data, cls.context)
        cls.model = cls.session.export()
        cls.nodes = cls.model['nodes']

    def node(self, name, language, kind=None):
        return next(n for n in self.nodes if n['name'] == name and (n['language'] == 'python') == (language == 'python') and (kind is None or n['kind'] == kind))

    def test_both_languages_and_alias_reexport(self):
        self.assertNotEqual(self.model['status'], 'failed', self.model['diagnostics'])
        for language, label in [('javascript','canUpload'),('python','can_upload')]:
            call = self.node(label, language, 'call')
            self.assertEqual(call['status'], 'resolved')
            target = self.session.by_id[call['targetId']]
            self.assertEqual(target['name'], 'permit')
            self.assertTrue(target['path'].endswith('access.ts' if language == 'javascript' else 'access.py'))

    def test_callback_unknown_recursion_and_constructor(self):
        for language in ('javascript','python'):
            self.assertIsNone(self.node('handler',language,'call')['targetId'])
            recurse = self.node('recursive',language,'call')
            self.assertEqual(self.session.by_id[recurse['targetId']]['name'], 'recursive')
            ctor = self.node('Store',language,'call')
            self.assertEqual(self.session.by_id[ctor['targetId']]['kind'], 'constructor')

    def test_shadowing_and_capture(self):
        for language in ('javascript','python'):
            keys = [n for n in self.nodes if n['name'] == 'key' and n['kind'] == 'variable' and (n['language'] == 'python') == (language=='python') and 'upload.' in n['path']]
            self.assertGreaterEqual(len(keys),2)
            self.assertEqual(len(keys),len({n['id'] for n in keys}))
            captures = [n for n in self.nodes if n['kind']=='reference' and n['name']=='key' and n.get('capture') and (n['language']=='python') == (language=='python')]
            self.assertTrue(captures)
            self.assertTrue(all(n['symbolId'] in {x['id'] for x in keys} for n in captures))

    def test_python_global_and_comprehension(self):
        update = self.node('update','python','function')
        shared = self.node('shared','python','variable')
        refs = [n for n in self.nodes if n['kind']=='reference' and n.get('functionId') == update['id'] and n['name']=='shared']
        self.assertTrue(refs)
        self.assertTrue(all(n['symbolId']==shared['id'] for n in refs))
        scopes=[n for n in self.nodes if n['kind']=='scope']
        self.assertTrue(scopes)
        self.assertTrue(any(n['kind']=='variable' and n['name']=='key' and n['ownerId'] in {s['id'] for s in scopes} for n in self.nodes))

    def test_logic_is_structural_and_keeps_finally(self):
        for language, name in [('javascript','uploadAsset'),('python','upload_asset')]:
            function=self.node(name,language,'function')
            result=self.session.query(dict(view='logic',focusId=function['id']))
            self.assertTrue(any('finally' in n.get('branch','') for n in result['nodes']))
            self.assertTrue(any(n.get('folded') for n in result['nodes']))
            self.assertTrue(all(r['kind'] != 'cfg' for r in result['relations']))
            self.assertTrue(result['variables'])

    def test_unicode_columns_and_repeat_identity(self):
        py = next(n for n in self.nodes if n['kind']=='reference' and n['path'].endswith('upload.py') and n['name']=='key' and n['range']['start'][0]==4)
        # AST byte columns are normalized to JS UTF-16 columns after emoji/Chinese.
        line=next(f for f in self.context['files'] if f['id']==py['path'])['content'].splitlines()[3]
        expected=len(line[:line.index('key')].encode('utf-16-le'))//2
        self.assertEqual(py['range']['start'][1], expected)
        repeated = run_language(self.context, 'python')
        self.assertEqual({n['id'] for n in repeated['nodes']}, {n['id'] for n in self.nodes if n['language']=='python'})

    def test_query_pagination_and_no_dangling_edges(self):
        for view in ('files','search'):
            result=self.session.query(dict(view=view,text='key',limit=2))
            self.assertLessEqual(len(result['nodes']),2)
            ids={n['id'] for n in result['nodes']}
            self.assertTrue(all(r['source'] in ids and r['target'] in ids for r in result['relations']))
        with self.assertRaises(ValueError): self.session.query(dict(view='files',limit=1000))

    def test_scan_schema_and_source_only_host(self):
        self.assertEqual(self.data['version'],1)
        self.assertNotIn('configs',self.data)
        self.assertNotIn('code',self.data)
        self.assertEqual(self.model['version'],1)
        # External platform calls remain unresolved; no installed package sources loaded.
        self.assertTrue(all(n['path'] in {f['id'] for f in self.context['files']} for n in self.nodes))

    def test_assignment_access_and_destructuring(self):
        for language in ('javascript','python'):
            function=self.node('scopes',language,'function')
            refs=[n for n in self.nodes if n['kind']=='reference' and n.get('functionId')==function['id']]
            self.assertTrue(any(n['access']=='write' for n in refs))
            self.assertTrue(any(n.get('access')=='readwrite' for n in self.nodes if (n['language']=='python')==(language=='python')))
        function=self.node('patterns','python','function')
        binding=next(n for n in self.nodes if n['kind']=='variable' and n['name']=='captured' and n['ownerId']==function['id'])
        self.assertTrue(self.session.references[binding['id']])

    def test_multiline_ranges_and_function_file_relations(self):
        call=next(n for n in self.nodes if n['kind']=='call' and n['name']=='canUpload' and n['range']['end'][0]>n['range']['start'][0])
        self.assertEqual(self.session.by_id[call['targetId']]['name'],'permit')
        graph=self.session.query(dict(view='functions',focusId='javascript/upload.ts'))
        self.assertTrue(any(r['kind']=='calls' for r in graph['relations']))
        focus=self.node('uploadAsset','javascript','function')
        graph=self.session.query(dict(view='functions',focusId=focus['id']))
        self.assertTrue(any(r.get('siteCount',0)>1 for r in graph['relations']))

    def test_typescript_call_hierarchy_keeps_constructor_sites_and_unknown_callbacks(self):
        focus = self.node('uploadAsset', 'javascript', 'function')
        result = self.session.query(dict(view='hierarchy', focusId=focus['id']))
        self.assertTrue(any(n['kind'] == 'constructor' for n in result['nodes']))
        self.assertTrue(any(n['kind'] == 'call' and n['name'] == 'handler' and n['status'] == 'unresolved' for n in result['nodes']))
        permit = self.node('permit', 'javascript', 'function')
        relation = next(r for r in result['relations'] if r['target'] == permit['id'])
        self.assertGreater(relation['siteCount'], 1)
        incoming = self.session.query(dict(view='hierarchy', focusId=permit['id'], direction='incoming'))
        self.assertTrue(any(r['source'] == focus['id'] and r['target'] == permit['id'] for r in incoming['relations']))
        self.assertTrue(all(r['source'] == focus['id'] for r in result['relations']))

    def test_global_reads_are_not_closure_captures(self):
        shared=self.node('shared','python','variable')
        self.assertTrue(all(not self.session.by_id[x]['capture'] for x in self.session.references[shared['id']]))

    def test_snapshot_sources_do_not_follow_disk_changes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'source.py'
            target.write_text('def original():\n    return 1\n')
            context={};data=scan_project(directory,snapshot_context=context)
            target.write_text('raise RuntimeError("do not execute or read")\n')
            result=CodeSession(data,context).export()
            self.assertTrue(any(n['name']=='original' for n in result['nodes']))
            self.assertFalse(any(n['kind']=='call' and n['name']=='RuntimeError' for n in result['nodes']))

    def test_captured_tsconfig_extends_and_type_only_calls(self):
        files=[dict(id='lib/helper.ts',content='export function work() { return 1; }',language='typescript',captureStatus='captured',parseStatus='parsed'),
               dict(id='app/main.ts',content="import {work as run} from '@lib/helper'; export function entry() { return run(); }",language='typescript',captureStatus='captured',parseStatus='parsed')]
        context=dict(files=files,configs={'tsconfig.json':'{"extends":"./tsconfig.base.json"}', 'tsconfig.base.json':'{"compilerOptions":{"baseUrl":".","paths":{"@lib/*":["lib/*"]}}}'},imports=[])
        model=run_language(context,'javascript')
        call=next(n for n in model['nodes'] if n['kind']=='call')
        self.assertEqual(call['status'],'resolved')
        self.assertEqual(next(n for n in model['nodes'] if n['id']==call['targetId'])['name'],'work')
        files[1]['content']="import type {work} from '@lib/helper'; work();"
        model=run_language(context,'javascript')
        call=next(n for n in model['nodes'] if n['kind']=='call')
        self.assertIsNone(call['targetId'])

    def test_declared_fixture_expectations(self):
        expected=json.loads((FIXTURE/'expected.json').read_text())
        for language in ('javascript','python'):
            for label,target_name in expected[language]['resolved'].items():
                calls=[n for n in self.nodes if n['kind']=='call' and n['name']==label and (n['language']=='python')==(language=='python')]
                self.assertTrue(calls,label)
                self.assertTrue(all(self.session.by_id[n['targetId']]['name']==target_name for n in calls))
            for label in expected[language]['unresolved']:
                self.assertIsNone(self.node(label,language,'call')['targetId'])
            function=self.node('upload_asset' if language=='python' else 'uploadAsset',language,'function')
            logic=self.session.query(dict(view='logic',focusId=function['id']))
            kinds={n['nodeType'] for n in logic['nodes']}
            self.assertTrue(set(expected[language]['logic']).issubset(kinds))

    def test_conditional_callable_signature_is_not_a_resolved_runtime_target(self):
        files=[dict(id='choice.ts',language='typescript',parseStatus='parsed',captureStatus='captured',content='function a() {} function b() {} const f = flag ? a : b; f();')]
        model=run_language(dict(files=files),'javascript')
        call=next(n for n in model['nodes'] if n['kind']=='call')
        self.assertNotEqual(call['status'],'resolved')

    def test_js_pattern_assignment_and_iteration_writes(self):
        text='let target = 0; [target] = items; ({value:target} = object); for(target of items) { console.log(target); }'
        model=run_language(dict(files=[dict(id='writes.ts',language='typescript',parseStatus='parsed',captureStatus='captured',content=text)]),'javascript')
        refs=[n for n in model['nodes'] if n['kind']=='reference' and n['name']=='target']
        self.assertEqual([n['access'] for n in refs],['write','write','write','read'])

    def test_ts_imported_variable_alias_in_shorthand_references_original_binding(self):
        files=[dict(id='a.ts',content='export const original = 1;',language='typescript',parseStatus='parsed',captureStatus='captured'),dict(id='b.ts',content="import {original as local} from './a'; const item = {local};",language='typescript',parseStatus='parsed',captureStatus='captured')]
        model=run_language(dict(files=files),'javascript')
        variable=next(n for n in model['nodes'] if n['kind']=='variable' and n['name']=='original')
        ref=next(n for n in model['nodes'] if n['kind']=='reference' and n['name']=='local')
        self.assertEqual(ref['symbolId'],variable['id'])

    def test_symtable_failure_isolated_to_invalid_file(self):
        model=analyze([dict(id='invalid.py',content='def bad():\n    nonlocal missing\n'),dict(id='valid.py',content='def valid():\n    return 1\n')])
        self.assertTrue(any(n['name']=='valid' for n in model['nodes']))
        self.assertTrue(any(d['path']=='invalid.py' for d in model['diagnostics']))

    def test_same_line_python_lambdas_have_distinct_symbol_tables(self):
        model=analyze([dict(id='lambda.py',content='x = 1\npair = (lambda: x, lambda x: x)\n')])
        param=next(n for n in model['nodes'] if n['kind']=='parameter' and n['name']=='x')
        ref=next(n for n in model['nodes'] if n['kind']=='reference' and n['ownerId']==param['ownerId'])
        self.assertEqual(ref['symbolId'],param['id'])

    @unittest.skipIf(sys.version_info < (3,12),'generic function syntax requires Python 3.12')
    def test_generic_python_function_global_uses_wrapped_function_scope(self):
        model=analyze([dict(id='generic.py',content='value=0\ndef update[T]():\n    global value\n    value=1\n    return value\n')])
        variables=[n for n in model['nodes'] if n['kind']=='variable' and n['name']=='value']
        self.assertEqual(len(variables),1)
        self.assertTrue(all(n['symbolId']==variables[0]['id'] for n in model['nodes'] if n['kind']=='reference' and n['name']=='value'))

    def test_invalid_python_retains_reason(self):
        result=analyze([dict(id='bad.py',content='def broken(:\n')])
        self.assertTrue(result['diagnostics'])
        self.assertEqual(result['nodes'],[])

if __name__=='__main__': unittest.main()
