import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

EXPERIMENTS = Path(__file__).resolve().parents[1] / "scripts" / "experiments"
sys.path.insert(0, str(EXPERIMENTS))
from joern_graphson import read_graphson
from joern_model import normalize, QueryIndex, source_column
from joern_process import run_process, tool_environment
from joern_probe import prepare, fixture_checks
from joern_semantics import reachable
from joern_syntax import syntax_checks


class ModelTests(unittest.TestCase):
    def raw(self, base=0):
        return dict(nodes=[
            dict(id=base+1,label="METHOD",name="outer",fullName="a.py:outer",filename="a.py",line=1,code="def outer():",order=1),
            dict(id=base+2,label="LOCAL",name="key",line=2,code="key",order=1),
            dict(id=base+3,label="IDENTIFIER",name="key",line=3,code="key",order=2),
            dict(id=base+4,label="CALL",name="target",line=3,code="target(key)",order=3),
            dict(id=base+5,label="METHOD",name="target",fullName="b.py:target",filename="b.py",line=1,code="def target(x):",order=1),
            dict(id=base+6,label="CALL",name="dynamic",line=3,code="dynamic()",order=4),
            dict(id=base+7,label="CALL",name="<operator>.assignment",line=2,code="key = 1",order=5),
        ], edges=[
            dict(source=base+1,target=base+i,label="AST") for i in (2,3,4,6,7)
        ]+[
            dict(source=base+3,target=base+2,label="REF"),
            dict(source=base+4,target=base+5,label="CALL"),
            dict(source=base+7,target=base+4,label="CFG"),
            dict(source=base+7,target=base+3,label="REACHING_DEF"),
        ])

    def model(self,base=0):
        return normalize(self.raw(base),{"a.py":"def outer():\n key = 1\n target(key); dynamic()\n","b.py":"def target(x): pass\n"},"snapshot","python","/snapshot")

    def test_ids_do_not_depend_on_joern_numeric_ids(self):
        self.assertEqual(self.model(),self.model(500))
        self.assertEqual(self.model()["coverage"]["identityCollisions"],0)

    def test_uncertain_calls_and_dataflow_remain_candidates(self):
        model=self.model()
        for edge in model["relations"]:
            if edge["kind"] in ("calls","dataDependency"):
                self.assertEqual(edge["status"],"candidate")
        self.assertEqual(len(model["unresolved"]),1)
        self.assertEqual(model["unresolved"][0]["code"],"dynamic()")
        self.assertEqual(next(x for x in model["objects"] if x["operator"])["kind"],"statement")

    def test_consumer_preserves_relationship_types(self):
        model=self.model()
        query=QueryIndex(model)
        outer=next(x["id"] for x in model["objects"] if x["name"]=="outer")
        self.assertEqual(len(query.function(outer)["calls"]),1)
        self.assertEqual({x["kind"] for x in query.logic(outer)}, {"references","controlFlow","dataDependency"})
        self.assertEqual(query.file_dependencies()[0]["target"],"b.py")
        self.assertIsNotNone(query.benchmark()["p50Ms"])

    def test_typed_graphson_adjacency_and_document(self):
        vertex={"id":{"@type":"g:Int64","@value":1},"label":"METHOD","properties":{"NAME":[{"value":"hello"}],"LINE_NUMBER":[{"value":{"@type":"g:Int32","@value":1}}]},"outE":{"AST":[{"inV":2}]}}
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/"graph.json"
            p.write_text(json.dumps(vertex)+"\n")
            raw=read_graphson(p)
            self.assertEqual(raw["nodes"][0]["name"],"hello")
            self.assertEqual(raw["nodes"][0]["line"],1)
            self.assertEqual(raw["edges"][0]["target"],"2")
            p.write_text(json.dumps({"vertices":[vertex],"edges":[]},indent=2))
            self.assertEqual(read_graphson(p),raw)
            vertex['properties']={'NAME':{'@type':'g:VertexProperty','@value':['hello']},'LINE_NUMBER':{'@type':'g:VertexProperty','@value':{'@type':'g:Int32','@value':1}}}
            p.write_text(json.dumps({'@type':'tinker:graph','@value':{'vertices':[vertex],'edges':[]}},indent=2))
            self.assertEqual(read_graphson(p),raw)

    def test_unicode_column_requires_source_match(self):
        text="const 中文 = '😀'; createKey("
        position=text.index('createKey')
        byte_position=len(text[:position].encode('utf-8'))
        utf16_position=len(text[:position].encode('utf-16-le'))//2
        for raw in (position,position+1,byte_position,utf16_position):
            self.assertEqual(source_column(text,'createKey(',raw),(position,'source-text-matched'))
        self.assertEqual(source_column(text,'missing',position),(None,'unverified'))

    def test_cfg_bypass_check_distinguishes_finally_path(self):
        from collections import defaultdict
        cfg=defaultdict(list,{'return':['cleanup'],'cleanup':['exit']})
        self.assertTrue(reachable('return',{'exit'},cfg))
        self.assertFalse(reachable('return',{'exit'},cfg,{'cleanup'}))
        cfg['return'].append('exit')
        self.assertTrue(reachable('return',{'exit'},cfg,{'cleanup'}))

    def test_invalid_python_is_detected_even_if_cpg_would_succeed(self):
        checks=syntax_checks({'python':{'broken.py':'def invalid(:'},'javascript':{}},{})
        self.assertEqual(checks['python']['status'],'checked')
        self.assertEqual(checks['diagnostics'][0]['path'],'broken.py')


class RunnerTests(unittest.TestCase):
    def test_capture_is_read_only_and_keeps_parser_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"project"; root.mkdir()
            (root/"main.py").write_text('def hello(): return "中文😀"\n')
            (root/"main.ts").write_text('export function hello() { return 1; }')
            (root/"large.ts").write_text('// comment\n'*60000)
            (root/".env.ts").write_text('const privateValue = 1;')
            before={p.name:p.read_bytes() for p in root.iterdir()}
            out=Path(temp)/"run";out.mkdir()
            project,entries,originals,languages,manifest=prepare(root,out)
            self.assertEqual(set(languages["python"]),{"main.py"})
            self.assertEqual(set(languages["javascript"]),{"main.ts"})
            self.assertEqual(before,{p.name:p.read_bytes() for p in root.iterdir()})
            self.assertEqual(next(e for e in entries if e["id"]=="large.ts")["parseStatus"],"skipped")
            self.assertTrue((out/"snapshot.json").is_file())

    def test_environment_is_local_and_does_not_mutate_parent(self):
        before=os.environ.copy()
        with tempfile.TemporaryDirectory() as temp:
            env=tool_environment('/local/jdk/bin/java',temp)
            self.assertIn('-Xmx4g',env['_JAVA_OPTIONS'])
            self.assertIn(str(Path(temp)/'jvm-home'),env['_JAVA_OPTIONS'])
            self.assertEqual(env['JAVA_HOME'],'/local/jdk')
        self.assertEqual(dict(os.environ),before)

    def test_process_failure_and_timeout_keep_logs(self):
        with tempfile.TemporaryDirectory() as temp, patch('joern_process.tree_rss',return_value=None):
            log=Path(temp)/'failure.log'
            result=run_process([sys.executable,'-c','raise SystemExit(7)'],temp,os.environ.copy(),log,5,use_system_time=False)
            self.assertEqual(result['status'],'failed')
            self.assertEqual(result['returncode'],7)
            result=run_process([sys.executable,'-c','import time; time.sleep(30)'],temp,os.environ.copy(),Path(temp)/'timeout.log',.1,use_system_time=False)
            self.assertEqual(result['status'],'timeout')
            self.assertTrue(log.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
