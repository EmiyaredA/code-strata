"""Source annotation fidelity, local rendering and safe element interaction."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from exploration.source_map import annotate, annotate_model, SourceMaps
from exploration.plantuml import serialize, sanitize_svg, UnsupportedDiagram
from exploration.uml_runtime import UmlRuntime, download, extract
from exploration.http import dispatch
from code_analysis.service import CodeSession
import test_uml as original_uml
example = original_uml.example


class SourceMapTests(unittest.TestCase):
    setUp, tearDown, begin, validate, publish = original_uml.UmlTests.setUp, original_uml.UmlTests.tearDown, original_uml.UmlTests.begin, original_uml.UmlTests.validate, original_uml.UmlTests.publish

    def test_callsite_owner_and_verified_target_definition(self):
        payload=self.store.snapshot(self.sid);session=CodeSession(payload['data'],payload['context']);session.build()
        refs=[dict(id='source',snapshotId=self.sid,path='migration.py',startLine=79,endLine=79,locationKind='source')]
        result=annotate(refs,session,self.store)
        self.assertEqual(result[0]['symbol']['name'],'convert_legacy')
        self.assertEqual(result[0]['association'],'callsite')
        target=next(r for r in result if r.get('symbol',{}).get('name')=='publish')
        self.assertEqual((target['startLine'],target['endLine']),(31,46))
        self.assertEqual(target['association'],'target-definition')
        self.assertEqual(refs[0].get('symbol'),None)
        # A broad region does not invent a single owning function or collect
        # every possible callee into the diagram element's displayed target.
        whole=annotate([dict(refs[0],startLine=1,endLine=90)],session,self.store)
        self.assertEqual(len(whole),1);self.assertNotIn('symbol',whole[0])

    def test_derived_cache_never_changes_stored_versions_and_enforces_project(self):
        doc=self.publish([example('activity',self.ev)])[0]
        before=json.dumps(self.store.diagram(str(self.project),doc['id']),sort_keys=True)
        maps=SourceMaps(self.store);result=maps.get(str(self.project),doc['id'])
        deadline=time.monotonic()+20
        while result['status']=='building' and time.monotonic()<deadline:
            time.sleep(.02);result=maps.get(str(self.project),doc['id'])
        self.assertEqual(result['status'],'ready')
        self.assertEqual(result['elements']['a'][0]['symbol']['name'],'convert_legacy')
        self.assertEqual(before,json.dumps(self.store.diagram(str(self.project),doc['id']),sort_keys=True))
        with self.assertRaises(LookupError):maps.get('/another-project',doc['id'])
        service=type('Service',(),dict(store=self.store,source_maps=maps,uml_runtime=UmlRuntime()))()
        status,response=dispatch(service,'GET',f"/api/explore/diagrams/{doc['id']}/source-map",dict(project=dict(root=str(self.project))),query='revision=1')
        self.assertEqual(status,200);self.assertEqual(response['status'],'ready')
        status,_=dispatch(service,'POST',f"/api/explore/diagrams/{doc['id']}/render",dict(project=dict(root=str(self.project))),dict(revision=1,source='arbitrary text'))
        self.assertEqual(status,422)

    def test_analyzer_drift_and_index_failure_are_explicit(self):
        doc=self.publish([example('activity',self.ev)])[0]
        maps=SourceMaps(self.store);entry={}
        with patch('exploration.source_map.fingerprint',return_value='new-analyzer'):
            maps._build(self.store.diagram(str(self.project),doc['id']),entry)
        self.assertEqual(entry['status'],'unavailable');self.assertEqual(entry['elements'],{})
        with patch('exploration.source_map.CodeSession.build',side_effect=ValueError('index failure')):
            maps._build(self.store.diagram(str(self.project),doc['id']),entry)
        self.assertEqual(entry['status'],'failed')


class PlantUmlTests(unittest.TestCase):
    def model(self,kind):
        return example(kind,'test-evidence')

    def test_seven_serializers_keep_source_ids_and_escape_labels(self):
        for kind in ('activity','sequence','class','component','state','usecase','deployment'):
            model=self.model(kind);model['nodes'][0]['label']='a"\n@enduml\n!include https://bad.invalid <img:x> [[https://bad]]'
            rendered=serialize(model)
            self.assertEqual(rendered['source'].count('\n@enduml\n'),1)
            self.assertNotIn('!include',rendered['source']);self.assertNotIn('[[https',rendered['source'])
            self.assertEqual(set(rendered['elements'].values()),{'a','b','ab'})
            self.assertEqual(rendered,serialize(model))

    def test_activity_branches_loops_and_unstructured_failure(self):
        def activity(roles,edges):
            return dict(type='activity',nodes=[dict(id=k,label=k,role=v) for k,v in roles.items()],edges=[dict(id=str(i),source=a,target=b,role='flow',guard=str(i)) for i,(a,b) in enumerate(edges)])
        diamond=activity(dict(s='start',d='decision',a='action',b='action',j='merge',e='end'),[('s','d'),('d','a'),('d','b'),('a','j'),('b','j'),('j','e')])
        result=serialize(diamond);self.assertIn('endif',result['source'])
        self.assertTrue({'a','b','d'}.issubset(set(result['elements'].values())))
        loop=activity(dict(s='start',d='decision',a='action',e='end'),[('s','d'),('d','a'),('d','e'),('a','d')])
        self.assertIn('endwhile',serialize(loop)['source'])
        bad=activity(dict(a='action',b='action',c='action'),[('a','b'),('a','c')])
        with self.assertRaises(UnsupportedDiagram):serialize(bad)

    def test_svg_allowlist_removes_active_and_external_content(self):
        raw='<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script><foreignObject/><image href="https://bad"/><a href="#uml_ok" onclick="evil()"><text>safe</text></a><a href="https://bad"><text>external</text></a><rect style="fill:url(https://bad)"/></svg>'
        clean=sanitize_svg(raw,{'uml_ok':'node-a'})
        for value in ('script','foreignObject','image','https','onclick'):
            self.assertNotIn(value,clean)
        self.assertIn('data-element="node-a"',clean);self.assertIn('tabindex="0"',clean)
        with self.assertRaises(ValueError):sanitize_svg('<!DOCTYPE svg><svg/>',{})

    @unittest.skipUnless(UmlRuntime().status()['status']=='ready','private PlantUML runtime not installed')
    def test_real_offline_seven_types_mapping_and_cache(self):
        runtime=UmlRuntime()
        for kind in ('activity','sequence','class','component','state','usecase','deployment'):
            with self.subTest(kind=kind):
                doc=dict(id=kind,revision=1,snapshotId='test',model=self.model(kind))
                rendered=runtime.render(doc)
                self.assertIn('<svg',rendered['svg'])
                self.assertNotIn('Syntax Error',rendered['svg'])
                self.assertIn('data-element="a"',rendered['svg'])
                self.assertIn('data-element="ab"',rendered['svg'])
                self.assertTrue(runtime.render(doc)['cached'])

    def test_missing_runtime_and_timeout_do_not_damage_interactive_model(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=UmlRuntime(directory);model=self.model('class');original=copy.deepcopy(model)
            doc=dict(id='x',revision=1,snapshotId='test',model=model)
            self.assertEqual(runtime.status()['status'],'missing')
            with self.assertRaises(LookupError):runtime.render(doc)
            with patch.object(runtime,'executables',return_value=(Path('/java'),Path('/jar'))),patch('exploration.uml_runtime.subprocess.run',side_effect=subprocess.TimeoutExpired('java',30)):
                with self.assertRaisesRegex(ValueError,'30 秒'):runtime.render(doc)
            self.assertTrue(runtime.slots.acquire(timeout=.1));runtime.slots.release()
            self.assertEqual(model,original)

    def test_install_checksum_failure_retry_and_archive_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            dest=Path(directory)
            response=io.BytesIO(b'wrong');response.headers={};response.geturl=lambda:'https://example.invalid'
            with patch('exploration.uml_runtime.urllib.request.urlopen',return_value=response):
                with self.assertRaisesRegex(ValueError,'SHA-256'):download(dict(url='https://example.invalid',sha256='0'*64),dest/'artifact')
            archive=dest/'bad.tar.gz'
            with tarfile.open(archive,'w:gz') as tar:
                entry=tarfile.TarInfo('../../outside');entry.size=1;tar.addfile(entry,io.BytesIO(b'x'))
            with self.assertRaises(tarfile.FilterError):extract(archive,dest/'stage')
            runtime=UmlRuntime(dest/'runtime')
            with patch('exploration.uml_runtime.cached_download',side_effect=OSError('offline')):
                runtime._install()
            self.assertEqual(runtime.status()['status'],'failed')
            with patch('threading.Thread.start') as start:
                self.assertEqual(runtime.install()['status'],'installing');start.assert_called_once()


if __name__=='__main__':unittest.main()
