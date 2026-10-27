"""Exercise auth, snapshot isolation and failure independence through HTTP."""
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from serve import make_server

ROOT=Path(__file__).resolve().parents[1]

class CodeApiTests(unittest.TestCase):
    def setUp(self):
        self.server=make_server(ROOT/'tests/fixtures/code-browser',node=os.environ.get('CODE_ARCHITECTURE_TEST_NODE'))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'
        with urlopen(self.base) as r: self.token=re.search('architecture-token" content="([^"]+)',r.read().decode()).group(1)
        with urlopen(Request(self.base+'/api/project',headers={'X-Architecture-Token':self.token})) as r: self.data=json.load(r)
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
    def request(self,body,token=None,origin=None):
        headers={'Content-Type':'application/json','X-Architecture-Token':self.token if token is None else token}
        if origin:headers['Origin']=origin
        with urlopen(Request(self.base+'/api/code/query',data=json.dumps(body).encode(),headers=headers),timeout=10) as r:return r.status,json.load(r)
    def test_auth_and_stale_snapshot(self):
        body=dict(snapshotId=self.data['snapshot']['id'],view='files')
        for opts,expected in [({'token':'bad'},403),({'origin':'https://foreign.example'},403)]:
            with self.assertRaises(HTTPError) as e:self.request(body,**opts)
            self.assertEqual(e.exception.code,expected);e.exception.close()
        with self.assertRaises(HTTPError) as e:self.request(dict(body,snapshotId='stale'))
        self.assertEqual(e.exception.code,409);e.exception.close()
    def test_async_index_and_bounded_query(self):
        body=dict(snapshotId=self.data['snapshot']['id'],view='files',limit=2)
        code,result=self.request(body)
        self.assertEqual(code,202)
        deadline=time.monotonic()+10
        while result['status']=='building' and time.monotonic()<deadline:
            time.sleep(.05);code,result=self.request(body)
        self.assertEqual(code,200);self.assertLessEqual(len(result['nodes']),2)
        ids={n['id'] for n in result['nodes']}
        self.assertTrue(all(r['source'] in ids and r['target'] in ids for r in result['relations']))
        self.assertGreater(result['remaining'],0)
        with urlopen(Request(self.base+'/api/project',headers={'X-Architecture-Token':self.token})) as r:self.assertEqual(json.load(r),self.data)
    def test_failed_analysis_does_not_change_project(self):
        with patch('code_analysis.service.run_language',side_effect=ValueError('test worker failed')):
            body=dict(snapshotId=self.data['snapshot']['id'],view='files')
            _,result=self.request(body)
            deadline=time.monotonic()+5
            while result['status']=='building' and time.monotonic()<deadline:
                time.sleep(.03);_,result=self.request(body)
            self.assertEqual(result['status'],'failed')
        with urlopen(Request(self.base+'/api/project',headers={'X-Architecture-Token':self.token})) as r:self.assertEqual(json.load(r),self.data)
