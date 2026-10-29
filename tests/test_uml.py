"""UML contracts, atomic shared documents and immutable evidence regressions."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from exploration.diagrams import KINDS, DiagramConflict, source_evidence, validate_diagrams
from exploration.store import Store
from exploration.snapshots import capture
from exploration.http import dispatch
from exploration.tools import RUN_TOOLS, validate_arguments


def example(kind, evidence):
    roles = {'activity': ('action', 'action', 'flow'), 'sequence': ('participant', 'participant', 'message'),
        'class': ('class', 'interface', 'implementation'), 'component': ('component', 'component', 'dependency'),
        'state': ('state', 'state', 'transition'), 'usecase': ('actor', 'usecase', 'association'),
        'deployment': ('device', 'artifact', 'dependency')}
    a,b,e = roles[kind]
    return dict(type=kind, title=kind+' 源码阅读', purpose='展示源码范围内的结构或流程；语义为源码推导。',
        nodes=[dict(id='a',label='入口',role=a,evidenceIds=[evidence],explanation='入口源码依据。'),
               dict(id='b',label='发布',role=b,evidenceIds=[evidence],explanation='发布源码依据。')],
        edges=[dict(id='ab',source='a',target='b',role=e,evidenceIds=[evidence],explanation='根据所引用的源码整理。',order=0)])


class UmlTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=os.environ.get('CODE_ARCHITECTURE_TEST_TMP'))
        self.project=Path(self.temp.name)/'project';self.project.mkdir()
        (self.project/'migration.py').write_text((ROOT/'tests/fixtures/uml_migration.py').read_text())
        self.store=Store(Path(self.temp.name)/'history.sqlite')
        self.sid,data,context=capture(self.project)
        self.store.save_snapshot(self.sid,str(self.project),data,context)
        self.conv=self.store.create(str(self.project),'codex','配置迁移')['id']
        self.run,self.ev=self.begin()

    def tearDown(self): self.temp.cleanup()

    def begin(self, conv=None, snapshot=None):
        run=self.store.start(conv or self.conv,'生成 UML')
        sid=snapshot or self.sid
        self.store.bind(run,sid)
        source=self.store.source(sid,'migration.py',49,90)
        return run,source_evidence(self.store,run,sid,source)

    def validate(self, diagrams, run=None, snapshot=None):
        return validate_diagrams(self.store,run or self.run,snapshot or self.sid,str(self.project),dict(diagrams=diagrams))

    def publish(self, diagrams, run=None, snapshot=None):
        run=run or self.run
        values=self.validate(diagrams,run,snapshot)
        self.store.save_diagram_draft(run,str(self.project),values)
        self.store.finish(run,'completed',diagrams=values)
        return values

    def test_seven_types_project_shared_and_old_versions_immutable(self):
        docs=self.publish([example(kind,self.ev) for kind in KINDS])
        self.assertEqual(len(self.store.list_diagrams(str(self.project))['diagrams']),7)
        other=self.store.create(str(self.project),'claude','另一会话')['id']
        run,ev=self.begin(other)
        changed=example('activity',ev);changed.update(id=docs[0]['id'],expectedRevision=1,title='更新后的流程')
        self.publish([changed],run)
        current=self.store.diagram(str(self.project),docs[0]['id'])
        old=self.store.diagram(str(self.project),docs[0]['id'],1)
        self.assertEqual(current['revision'],2)
        self.assertNotEqual(current['model']['title'],old['model']['title'])
        self.assertEqual(len(self.store.diagram_versions(str(self.project),docs[0]['id'])),2)
        self.assertEqual(self.store.diagram_source(str(self.project),docs[0]['id'],1,'migration.py',76,76)['content'].strip(),'publish(backup, original.decode("utf-8"))')

    def test_invalid_batch_never_writes_partial_diagrams(self):
        valid=example('activity',self.ev);bad=example('sequence',self.ev)
        bad['edges'][0]['target']='missing'
        with self.assertRaises(ValueError): self.publish([valid,bad])
        self.assertEqual(self.store.list_diagrams(str(self.project))['diagrams'],[])
        for mutation in ('unknown','html','role','duplicate','budget','field','node-explanation','edge-explanation'):
            value=copy.deepcopy(valid)
            if mutation=='unknown':value['nodes'][0]['evidenceIds']=['fake']
            if mutation=='html':value['nodes'][0]['label']='<script>alert(1)</script>'
            if mutation=='role':value['nodes'][0]['role']='class'
            if mutation=='duplicate':value['nodes'][1]['id']='a'
            if mutation=='budget':value['nodes']=value['nodes']*51
            if mutation=='field':value['nodes'][0]['onClick']='evil'
            if mutation=='node-explanation':value['nodes'][0].pop('explanation')
            if mutation=='edge-explanation':value['edges'][0]['explanation']=''
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):self.validate([value])

    def test_canonical_candidate_status_is_preserved_not_authored(self):
        span=dict(start=[76,0],end=[76,40])
        self.store.record_facts(self.run,dict(nodes=[dict(id='fn1',kind='function',path='migration.py',range=span,status='resolved'),dict(id='fn2',kind='function',path='migration.py',range=span,status='resolved')],relations=[dict(id='call',kind='calls',source='fn1',target='fn2',path='migration.py',range=span,status='candidate')]))
        value=example('sequence',self.ev)
        value['nodes'][0]['evidenceIds']=['fn1'];value['nodes'][1]['evidenceIds']=['fn2'];value['edges'][0]['evidenceIds']=['call']
        model=self.validate([value])[0]['model']
        self.assertEqual((model['edges'][0]['basis'],model['edges'][0]['status']),('analyzer','candidate'))
        value['nodes'][1]['evidenceIds']=[self.ev]
        model=self.validate([value])[0]['model']
        self.assertEqual(model['edges'][0]['basis'],'inferred')
        self.assertEqual(model['edges'][0]['status'],'candidate')

    def test_concurrent_conflict_preserves_entire_batch_and_draft(self):
        docs=self.publish([example('activity',self.ev),example('sequence',self.ev)])
        conv2=self.store.create(str(self.project),'codex','并发会话')['id']
        r2,e2=self.begin(conv2);stale=[]
        for doc,kind in zip(docs,('activity','sequence')):
            value=example(kind,e2);value.update(id=doc['id'],expectedRevision=1);stale.append(value)
        pending=self.validate(stale,r2);self.store.save_diagram_draft(r2,str(self.project),pending)
        r3,e3=self.begin();winner=example('sequence',e3);winner.update(id=docs[1]['id'],expectedRevision=1)
        self.publish([winner],r3)
        with self.assertRaises(DiagramConflict):self.store.finish(r2,'completed',diagrams=pending)
        self.store.finish(r2,'failed',error='conflict')
        self.assertEqual(self.store.diagram(str(self.project),docs[0]['id'])['revision'],1)
        self.assertEqual(self.store.diagram(str(self.project),docs[1]['id'])['revision'],2)
        self.assertEqual(len(self.store.diagram_draft(str(self.project),r2)['diagrams']),2)

    def test_failed_cancelled_and_interrupted_runs_cannot_publish(self):
        for status in ('failed','cancelled','interrupted'):
            if status=='failed':run,ev=self.run,self.ev
            else:run,ev=self.begin()
            values=self.validate([example('activity',ev)],run)
            self.store.finish(run,status,diagrams=values)
            self.store.finish(run,'completed',diagrams=values)
        self.assertFalse(self.store.list_diagrams(str(self.project))['diagrams'])

    def test_changes_unrelated_files_delete_rename_and_snapshot_read(self):
        doc=self.publish([example('activity',self.ev)])[0]['id']
        self.assertEqual(self.store.check_diagram(str(self.project),doc)['status'],'current')
        (self.project/'unrelated.py').write_text('x = 1\n')
        self.assertEqual(self.store.check_diagram(str(self.project),doc)['status'],'current')
        original=(self.project/'migration.py').read_text()
        (self.project/'migration.py').write_text('# changed\n'+original)
        self.assertEqual(self.store.check_diagram(str(self.project),doc)['files'][0]['status'],'modified')
        self.assertEqual(self.store.diagram_source(str(self.project),doc,1,'migration.py',79,79)['content'].strip(),'publish(path, encode(document))')
        (self.project/'migration.py').rename(self.project/'renamed.py')
        self.assertEqual(self.store.check_diagram(str(self.project),doc)['files'][0]['status'],'deleted')
        self.assertIn('publish(path',self.store.diagram_source(str(self.project),doc,1,'migration.py',79,79)['content'])

    def test_update_requeries_new_snapshot_and_keeps_old_line_numbers(self):
        doc=self.publish([example('activity',self.ev)])[0]['id']
        path=self.project/'migration.py';path.write_text('# new first line\n'+path.read_text())
        sid,data,context=capture(self.project);self.store.save_snapshot(sid,str(self.project),data,context)
        run,ev=self.begin(snapshot=sid)
        update=example('activity',ev);update.update(id=doc,expectedRevision=1)
        self.publish([update],run,sid)
        self.assertEqual(self.store.diagram(str(self.project),doc,1)['snapshotId'],self.sid)
        self.assertEqual(self.store.diagram(str(self.project),doc)['snapshotId'],sid)
        self.assertIn('publish(path',self.store.diagram_source(str(self.project),doc,2,'migration.py',80,80)['content'])
        self.assertIn('publish(path',self.store.diagram_source(str(self.project),doc,1,'migration.py',79,79)['content'])

    def test_project_membership_and_capture_boundaries(self):
        doc=self.publish([example('activity',self.ev)])[0]['id']
        with self.assertRaises(LookupError):self.store.diagram('/different/project',doc)
        with self.assertRaises(LookupError):self.store.diagram_source(str(self.project),doc,1,'../history.sqlite',1,10)
        with self.assertRaises(LookupError):self.store.diagram_source(str(self.project),doc,1,'/etc/passwd',1,10)
        with self.assertRaises(ValueError):self.store.list_diagrams(str(self.project),-1)
        self.assertIsNotNone(self.store.list_diagrams(str(self.project),limit=1))
        (self.project/'migration.py').unlink();(self.project/'migration.py').symlink_to('/etc/passwd')
        self.assertEqual(self.store.check_diagram(str(self.project),doc)['files'][0]['status'],'error')

    def test_legacy_import_idempotent_and_not_relabeled_as_uml(self):
        legacy=dict(title='旧图',view='functions',nodes=[],relations=[],snapshotId=self.sid,runId=self.run,explanation='旧说明')
        self.store.finish(self.run,'completed',view=legacy)
        for _ in range(2):Store(self.store.path)
        docs=self.store.list_diagrams(str(self.project))['diagrams']
        self.assertEqual(len(docs),1);self.assertEqual(docs[0]['type'],'legacy');self.assertEqual(docs[0]['revision'],1)

    def test_http_routes_scope_batch_checks_and_tool_contract(self):
        doc=self.publish([example('activity',self.ev)])[0]['id']
        service=type('Service',(),{'store':self.store})()
        current=dict(project=dict(root=str(self.project)))
        status,body=dispatch(service,'GET','/api/explore/diagrams',current)
        self.assertEqual(status,200);self.assertEqual(body['diagrams'][0]['id'],doc)
        status,body=dispatch(service,'POST','/api/explore/diagrams/check',current,dict(diagrams=[dict(id=doc,revision=1)]))
        self.assertEqual(status,200);self.assertEqual(body['checks'][0]['status'],'current')
        status,_=dispatch(service,'GET','/api/explore/diagrams/'+doc,dict(project=dict(root='/other')))
        self.assertEqual(status,404)
        validate_arguments('save_diagrams',dict(diagrams=[example('activity',self.ev)]),RUN_TOOLS)
        status,_=dispatch(service,'POST',f'/api/explore/diagrams/{doc}/source',current,dict(path='../history.sqlite',revision=1))
        self.assertEqual(status,404)

    def test_real_migration_backup_publish_and_validation_order(self):
        content=(self.project/'migration.py').read_text().splitlines()
        self.assertIn('publish(backup, original.decode',content[75])
        self.assertIn('publish(path, encode(document))',content[78])
        self.assertIn('if read_config(path) != values:',content[79])
        ids={}
        for line in (63,69,76,77,79,80):
            ids[line]=source_evidence(self.store,self.run,self.sid,self.store.source(self.sid,'migration.py',line,65 if line==63 else line))
        doc=example('activity',ids[63]);doc['nodes']=[];doc['edges']=[]
        labels=['加锁','读取','备份','检查原文件','发布','回读校验']
        lines=list(ids)
        for i,line in enumerate(lines):
            doc['nodes'].append(dict(id=str(line),label=labels[i],role='action',evidenceIds=[ids[line]],explanation=f'依据 L{line}。'))
            if i:doc['edges'].append(dict(id=f'e{i}',source=str(lines[i-1]),target=str(line),role='flow',evidenceIds=[ids[lines[i-1]],ids[line]],explanation='源码顺序。'))
        model=self.validate([doc])[0]['model']
        self.assertEqual([(e['source'],e['target']) for e in model['edges']],[('63','69'),('69','76'),('76','77'),('77','79'),('79','80')])
        self.assertEqual(model['nodes'][2]['evidence'][0]['startLine'],76)

    def test_multi_site_relations_keep_separate_call_lines_and_decoration_inherits(self):
        sites=[dict(path='migration.py',range=dict(start=[line,0],end=[line,20])) for line in (76,79)]
        self.store.record_facts(self.run,dict(relations=[dict(id='calls',kind='calls',source='a',target='b',sites=sites,status='resolved')]))
        value=example('activity',self.ev)
        value['edges'][0]['evidenceIds']=['calls']
        value['nodes'].append(dict(id='end',label='',role='end',evidenceIds=[]))
        value['edges'].append(dict(id='end-flow',source='b',target='end',role='flow',evidenceIds=[]))
        model=self.validate([value])[0]['model']
        self.assertEqual([r['startLine'] for r in model['edges'][0]['evidence']],[76,79])
        self.assertTrue(model['nodes'][-1]['evidence'])
        self.assertEqual({r['locationKind'] for r in model['edges'][0]['evidence']},{'call'})

    def test_type_specific_sequence_and_container_structure(self):
        value=example('sequence',self.ev)
        value['edges'].append(dict(value['edges'][0],id='second'))
        with self.assertRaises(ValueError):self.validate([value])
        value=example('class',self.ev)
        value['nodes'][1]['parentId']='a'
        with self.assertRaises(ValueError):self.validate([value])
