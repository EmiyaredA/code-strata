"""All notation contracts, source immutability and native/local render coverage."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from uml_examples import NOTATION_SOURCE, examples
from exploration.diagrams import validate_diagrams, source_evidence
from exploration.diagram_types import KINDS
from exploration.plantuml import render_projection
from exploration.uml_runtime import UmlRuntime
from exploration.store import Store
from exploration.snapshots import capture

class NotationTests(unittest.TestCase):
 def setUp(self):
    self.tmp=tempfile.TemporaryDirectory();self.project=Path(self.tmp.name)/'project';self.project.mkdir();(self.project/'notation.py').write_text(NOTATION_SOURCE)
    self.store=Store(Path(self.tmp.name)/'history.sqlite3');self.sid,data,ctx=capture(self.project);self.store.save_snapshot(self.sid,str(self.project),data,ctx)
    self.conv=self.store.create(str(self.project),'codex','类型验收')['id'];self.run=self.store.start(self.conv,'生成全部图');self.store.bind(self.run,self.sid)
    self.ev=source_evidence(self.store,self.run,self.sid,self.store.source(self.sid,'notation.py',1,14));self.docs=examples(self.ev)
 def tearDown(self):self.tmp.cleanup()
 def validate(self,d):return validate_diagrams(self.store,self.run,self.sid,str(self.project),dict(diagrams=[d]))[0]
 def test_all_sixteen_contracts_keep_evidence_and_version_is_immutable(self):
    self.assertEqual({d['type'] for d in self.docs},set(KINDS));values=[self.validate(d) for d in self.docs]
    self.store.finish(self.run,'completed',diagrams=values)
    for v in values:
      model=self.store.diagram(str(self.project),v['id'])['model'];self.assertEqual(model['schemaVersion'],2)
      for item in model['nodes']+model['edges']:self.assertTrue(item['evidence']);self.assertEqual(item['evidence'][0]['snapshotId'],self.sid)
    old=self.store.diagram(str(self.project),values[0]['id'],1);before=json.dumps(old,sort_keys=True)
    (self.project/'notation.py').unlink()
    self.assertIn('class Service',self.store.diagram_source(str(self.project),values[0]['id'],1,'notation.py',1,14)['content'])
    self.assertEqual(before,json.dumps(self.store.diagram(str(self.project),values[0]['id'],1),sort_keys=True))
 def test_typed_fields_and_semantic_endpoints_reject_invalid_input(self):
    for kind,mutate in [('swimlane',lambda d:d['nodes'][-1].pop('parentId')),('profile',lambda d:d['edges'][0].update(source='meta',target='stereo')),('composite',lambda d:d['nodes'][2].pop('portKind')),('timing',lambda d:d['nodes'][1].pop('order')),('object',lambda d:d['nodes'][0].update(slots='not-a-list')),('communication',lambda d:d['edges'].append(dict(d['edges'][0],id='duplicate'))),('class',lambda d:d['nodes'][0].update(portKind='provided'))]:
      with self.subTest(kind=kind):
       doc=copy.deepcopy(next(d for d in self.docs if d['type']==kind));mutate(doc)
       with self.assertRaises(ValueError):self.validate(doc)
    doc=copy.deepcopy(next(d for d in self.docs if d['type']=='timing'));doc['nodes'][1]['time']=4
    with self.assertRaisesRegex(ValueError,'timeUnit'):self.validate(doc)
    doc['timeUnit']='ms'
    with self.assertRaises(ValueError):self.validate(doc)
 def test_missing_evidence_and_markup_never_save(self):
    for kind in KINDS:
      doc=copy.deepcopy(next(d for d in self.docs if d['type']==kind));n=next(n for n in doc['nodes'] if n['role'] not in ('start','end','fork','join','merge'));n['evidenceIds']=[]
      with self.subTest(kind=kind),self.assertRaises(ValueError):self.validate(doc)
 def test_local_render_does_not_require_java_and_keeps_all_ids(self):
    runtime=UmlRuntime(Path(self.tmp.name)/'no-runtime')
    for kind in ('flowchart','composite','profile','communication','interaction-overview'):
      v=self.validate(next(d for d in self.docs if d['type']==kind));model=v['model'];before=copy.deepcopy(model)
      with patch.object(runtime,'executables',side_effect=AssertionError('must not require Java')):
       r=runtime.render(dict(id=v['id'],revision=1,snapshotId=self.sid,model=model))
      self.assertEqual(r['renderer'],'local-svg');self.assertEqual(set(r['elements'].values()),{n['id'] for n in model['nodes']+model['edges']});self.assertEqual(model,before)
 def test_irreducible_activity_uses_local_svg_without_rewriting_edges(self):
    d=copy.deepcopy(next(d for d in self.docs if d['type']=='activity'));d['edges'].append(dict(d['edges'][0],id='back',source='verify',target='lock'))
    m=self.validate(d)['model'];r=render_projection(m);self.assertEqual(r['renderer'],'local-svg');self.assertEqual(r['model']['edges'],m['edges'])
 @unittest.skipUnless(UmlRuntime().status()['status']=='ready','private runtime not installed')
 def test_native_types_render_offline_with_every_element_accessible(self):
    runtime=UmlRuntime()
    for d in self.docs:
      m=self.validate(d)['model'];projection=render_projection(m)
      if projection['renderer']!='plantuml':continue
      with self.subTest(kind=d['type']):
       r=runtime.render(dict(id=d['type'],revision=1,snapshotId=self.sid,model=m))
       self.assertIn('<svg',r['svg']);self.assertNotIn('Syntax Error',r['svg'])
       for item in m['nodes']+m['edges']:self.assertIn('data-element="'+item['id']+'"',r['svg'])
       self.assertTrue(runtime.render(dict(id=d['type'],revision=1,snapshotId=self.sid,model=m))['cached'])
