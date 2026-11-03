"""Project diagram lifecycle, management intents and old snapshot compatibility."""
import unittest
import test_uml as uml
example=uml.example
from exploration.diagrams import DiagramConflict, validate_diagrams
from exploration.store import Store
from exploration.http import dispatch


class DiagramManagementTests(unittest.TestCase):
    setUp=uml.UmlTests.setUp
    tearDown=uml.UmlTests.tearDown
    begin=uml.UmlTests.begin
    validate=uml.UmlTests.validate
    publish=uml.UmlTests.publish

    def test_trash_restore_keeps_versions_source_and_project_boundary(self):
        doc=self.publish([example('activity',self.ev)])[0]['id'];project=str(self.project)
        before=self.store.diagram(project,doc)
        deleted=self.store.set_diagram_deleted(project,doc,1,0,True)
        self.assertEqual(deleted['lifecycleVersion'],1)
        self.assertFalse(self.store.list_diagrams(project)['diagrams'])
        self.assertEqual(self.store.list_diagrams(project,state='trashed')['diagrams'][0]['id'],doc)
        with self.assertRaises(LookupError):self.store.diagram(project,doc)
        with self.assertRaises(LookupError):self.store.set_diagram_deleted('/other',doc,1,1,False)
        with self.assertRaises(DiagramConflict):self.store.set_diagram_deleted(project,doc,1,0,False)
        self.store=Store(self.store.path)
        restored=self.store.set_diagram_deleted(project,doc,1,1,False)
        self.assertEqual(restored['lifecycleVersion'],2)
        self.assertEqual(restored['model'],before['model'])
        self.assertEqual(len(self.store.diagram_versions(project,doc)),1)
        self.assertIn('publish(path',self.store.diagram_source(project,doc,1,'migration.py',79,79)['content'])

    def test_deleted_then_restored_document_rejects_already_validated_pending_update(self):
        doc=self.publish([example('activity',self.ev)])[0]['id'];project=str(self.project)
        run,ev=self.begin();value=example('activity',ev);value.update(id=doc,expectedRevision=1)
        pending=self.validate([value],run);self.store.save_diagram_draft(run,project,pending)
        self.store.set_diagram_deleted(project,doc,1,0,True)
        with self.assertRaises(DiagramConflict):self.store.finish(run,'completed',diagrams=pending)
        self.store.set_diagram_deleted(project,doc,1,1,False)
        with self.assertRaises(DiagramConflict):self.store.finish(run,'completed',diagrams=pending)
        self.assertEqual(self.store.diagram(project,doc)['revision'],1)
        self.assertEqual(self.store.diagram_draft(project,run)['diagrams'],pending)

    def test_lifecycle_is_captured_at_run_start_not_at_late_save(self):
        doc=self.publish([example('activity',self.ev)])[0]['id'];project=str(self.project)
        run,ev=self.begin();lifecycles=self.store.diagram_lifecycles(project)
        self.store.set_diagram_deleted(project,doc,1,0,True);self.store.set_diagram_deleted(project,doc,1,1,False)
        value=example('activity',ev);value.update(id=doc,expectedRevision=1)
        pending=validate_diagrams(self.store,run,self.sid,project,dict(diagrams=[value]),lifecycles=lifecycles)
        with self.assertRaises(DiagramConflict):self.store.finish(run,'completed',diagrams=pending)

    def test_management_requires_one_new_or_exact_target_and_matching_type(self):
        doc=self.publish([example('activity',self.ev)])[0]['id'];project=str(self.project)
        run,ev=self.begin();target=self.store.diagram(project,doc)
        target=dict(id=doc,expectedRevision=1,lifecycleVersion=0,model=target['model'])
        def validate(values,operation='create',kind='auto'):
            return validate_diagrams(self.store,run,self.sid,project,dict(diagrams=values),target if operation=='update' else None,False,operation,kind)
        value=example('activity',ev)
        for values in ([value,value],[dict(value,id=doc,expectedRevision=1)]):
            with self.assertRaises(ValueError):validate(values)
        with self.assertRaises(ValueError):validate([value],kind='sequence')
        with self.assertRaises(ValueError):validate([value],operation='update')
        changed=example('sequence',ev);changed.update(id=doc,expectedRevision=1)
        with self.assertRaises(ValueError):validate([changed],operation='update')
        value.update(id=doc,expectedRevision=1)
        self.assertEqual(validate([value],operation='update')[0]['id'],doc)

    def test_legacy_deleted_import_does_not_revive_and_converted_version_survives_restart(self):
        project=str(self.project)
        legacy=dict(title='旧图',view='functions',nodes=[],relations=[],snapshotId=self.sid,runId=self.run,explanation='旧说明')
        self.store.finish(self.run,'completed',view=legacy)
        doc=self.store.list_diagrams(project)['diagrams'][0]['id']
        self.store.set_diagram_deleted(project,doc,1,0,True)
        self.store=Store(self.store.path)
        self.assertFalse(self.store.list_diagrams(project)['diagrams'])
        self.store.set_diagram_deleted(project,doc,1,1,False)
        run,ev=self.begin();value=example('activity',ev);value.update(id=doc,expectedRevision=1)
        target=self.store.diagram(project,doc);target.update(expectedRevision=1)
        pending=validate_diagrams(self.store,run,self.sid,project,dict(diagrams=[value]),target,True,'update','auto')
        self.store.finish(run,'completed',diagrams=pending)
        self.store=Store(self.store.path)
        self.assertEqual(self.store.diagram(project,doc)['model']['type'],'activity')
        self.assertEqual(self.store.diagram(project,doc)['revision'],2)
        self.assertEqual(self.store.diagram(project,doc,1)['model']['type'],'legacy')

    def test_management_http_search_pagination_restore_and_conflict(self):
        values=[example('activity',self.ev),example('sequence',self.ev)]
        values[0]['title']='配置迁移';values[1]['title']='启动顺序'
        docs=self.publish(values);project=str(self.project)
        service=type('Service',(),{'store':self.store})();current=dict(project=dict(root=project))
        path='/api/explore/diagrams/'+docs[0]['id']
        code,result=dispatch(service,'GET','/api/explore/diagrams',current,query='q=配置&limit=1')
        self.assertEqual((code,len(result['diagrams'])),(200,1))
        body=dict(expectedRevision=1,lifecycleVersion=0)
        self.assertEqual(dispatch(service,'POST',path+'/trash',current,body)[0],200)
        self.assertEqual(dispatch(service,'POST',path+'/restore',current,body)[0],409)
        self.assertEqual(dispatch(service,'POST',path+'/restore',dict(project=dict(root='/other')),dict(expectedRevision=1,lifecycleVersion=1))[0],404)
        code,result=dispatch(service,'GET','/api/explore/diagrams',current,query='state=trashed')
        self.assertEqual(result['diagrams'][0]['title'],'配置迁移')
        code,result=dispatch(service,'POST','/api/explore/diagrams/check',current,dict(diagrams=[dict(id=d['id'],revision=1) for d in docs]))
        self.assertEqual(code,200);self.assertEqual([c['status'] for c in result['checks']],['unavailable','current'])
