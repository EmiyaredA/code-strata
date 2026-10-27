import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from scan import scan_project
from serve import make_server

NODE = os.environ.get('CODE_ARCHITECTURE_TEST_NODE')
class ScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('CODE_ARCHITECTURE_TEST_TMP'))
        self.root = Path(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()
    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path
    def scan(self, mapping=None):
        return scan_project(self.root, mapping, NODE)
    def test_python_ast_and_read_only(self):
        self.write('pkg/__init__.py','')
        self.write('pkg/guard.py','def allowed(): return True\n')
        self.write('pkg/save.py','# from imaginary import fake\nfrom .guard import allowed\ntext="import not_a_dependency"\n')
        before={p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        data=self.scan()
        self.assertEqual([(r['from'],r['to'],r['line']) for r in data['imports']],[('pkg/save.py','pkg/guard.py',2)])
        self.assertEqual(before,{p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertEqual(data['files'][1]['language'],'python')
    def test_ts_alias_workspace_reexport_and_dynamic(self):
        self.write('tsconfig.json',json.dumps({'compilerOptions':{'baseUrl':'.','paths':{'@/*':['src/*']}}}))
        self.write('src/check.ts','export function check() {}')
        self.write('packages/lib/package.json',json.dumps({'name':'@demo/lib','source':'src/index.ts'}))
        self.write('packages/lib/src/index.ts','export const a = 1;')
        self.write('src/main.ts','import {check} from "@/check";\nexport {a} from "@demo/lib";\nconst x=import(variable);\n// import "./not-real"\n')
        data=self.scan()
        self.assertEqual({r['to'] for r in data['imports']},{'src/check.ts','packages/lib/src/index.ts'})
        self.assertTrue(any(d['kind']=='dynamic' for d in data['diagnostics']))
        self.assertFalse(any('not-real' in d.get('message','') for d in data['diagnostics']))
    def test_missing_reference_does_not_become_edge(self):
        self.write('a.ts','import x from "./missing";')
        data=self.scan()
        self.assertEqual(data['imports'],[])
        self.assertTrue(any(d['kind']=='unresolved' for d in data['diagnostics']))
    def test_mapping_shared_members_and_evidence_projection(self):
        self.write('ui/panel.py','from core.save import save')
        self.write('core/save.py','def save(): return 1')
        self.write('core/types.py','class Document: pass')
        mapping=self.write('map.json',json.dumps({'version':1,'groups':[
            {'id':'ui','title':'界面','files':['ui/panel.py','core/types.py'],'origin':'confirmed'},
            {'id':'core','title':'保存','files':['core/save.py','core/types.py'],'origin':'inferred'}]}))
        data=self.scan(mapping)
        self.assertEqual(len(data['edges']),1)
        self.assertEqual(data['edges'][0]['evidence'][0]['from'],'ui/panel.py')
        self.assertEqual([g['id'] for g in data['groups'] if 'core/types.py' in g['files']],['ui','core'])
        self.write('core/save.py','def renamed(): return 2')
        changed=self.scan(mapping)
        self.assertNotEqual(data['snapshot']['id'],changed['snapshot']['id'])
    def test_stale_mapping_and_duplicate_ids(self):
        self.write('a.py','x=1')
        mapping=self.write('map.json',json.dumps({'version':1,'groups':[{'id':'one','title':'模块','files':['a.py','gone.py']}]}))
        data=self.scan(mapping)
        self.assertEqual(data['groups'][0]['files'],['a.py'])
        self.assertEqual(data['groups'][0]['origin'],'inferred')
        self.assertTrue(any(d['kind']=='mapping' for d in data['diagnostics']))
        mapping.write_text(json.dumps({'version':1,'groups':[{'id':'one','title':'A','files':[]},{'id':'one','title':'B','files':[]}]}))
        with self.assertRaises(ValueError): self.scan(mapping)
    def test_shared_internal_member_does_not_invent_cross_group_edge(self):
        self.write('save.py','from shared import Document')
        self.write('read.py','from shared import Document')
        self.write('shared.py','class Document: pass')
        mapping=self.write('map.json',json.dumps({'version':1,'groups':[
            {'id':'save','title':'保存','files':['save.py','shared.py']},
            {'id':'read','title':'读取','files':['read.py','shared.py']}]}))
        data=self.scan(mapping)
        self.assertEqual(len(data['imports']),2)
        self.assertEqual(data['edges'],[])
    def test_gitignore_and_symbolic_links(self):
        self.write('visible.py','x=1')
        self.write('hidden.py','x=2')
        self.write('.gitignore','hidden.py\n')
        self.write('node_modules/pkg/dependency.ts','const x=1')
        self.write('.env.ts','const secret=1')
        (self.root/'linked.py').symlink_to(self.root/'visible.py')
        subprocess.run(['git','init','-q',str(self.root)],check=True)
        self.assertEqual([f['id'] for f in self.scan()['files']],['visible.py'])
    def test_parser_unavailable_and_invalid_python_are_visible(self):
        self.write('broken.py','def invalid(')
        self.write('main.ts','export const value=1')
        data=scan_project(self.root,node='/nonexistent/node')
        self.assertEqual(len(data['files']),2)
        self.assertTrue(any(d['kind']=='syntax' for d in data['diagnostics']))
        self.assertTrue(any(d['kind']=='parser' for d in data['diagnostics']))
    def test_config_changes_snapshot(self):
        self.write('src/main.ts','export const x=1')
        config=self.write('tsconfig.json','{}')
        before=self.scan()['snapshot']['id']
        config.write_text('{"compilerOptions":{"strict":true}}')
        self.assertNotEqual(before,self.scan()['snapshot']['id'])
    def test_server_origin_token_and_failed_switch(self):
        self.write('main.py','value=1')
        server=make_server(node=NODE)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            html=urlopen(base).read().decode()
            token=re.search('architecture-token" content="([^"]+)',html).group(1)
            def send(body=None,origin=None,auth=token):
                headers={'X-Architecture-Token':auth}
                if origin:headers['Origin']=origin
                if body is not None:headers['Content-Type']='application/json'
                return urlopen(Request(base+'/api/project',data=None if body is None else json.dumps(body).encode(),headers=headers),timeout=15)
            with self.assertRaises(HTTPError) as rejected:send(auth='wrong')
            self.assertEqual(rejected.exception.code,403)
            with self.assertRaises(HTTPError):send({'path':str(self.root)},origin='https://external.example')
            data=json.load(send({'path':str(self.root)}))
            with self.assertRaises(HTTPError):send({'path':'/does-not-exist'})
            self.assertEqual(json.load(send())['snapshot']['id'],data['snapshot']['id'])
            with self.assertRaises(HTTPError):urlopen(base+'/scripts/scan.py')
        finally:
            server.shutdown();server.server_close();worker.join()

if __name__=='__main__':unittest.main(verbosity=2)
