"""The five actual CLI adapters carry the UML tool schema and batch results."""
import unittest
import os
import time
from unittest.mock import patch
from urllib.error import HTTPError
import test_exploration as helpers

class UmlTransportTests(unittest.TestCase):
    setUp = helpers.ExplorationTests.setUp
    tearDown = helpers.ExplorationTests.tearDown
    open_server = helpers.ExplorationTests.open_server
    close_server = helpers.ExplorationTests.close_server
    api = helpers.ExplorationTests.api
    create = helpers.ExplorationTests.create
    wait = helpers.ExplorationTests.wait
    run_agent = helpers.ExplorationTests.run_agent

    def test_all_five_native_transports_publish_project_shared_uml(self):
        for agent in ('codex', 'opencode', 'dsh', 'claude', 'pi'):
            with self.subTest(agent=agent):
                identifier = self.create(agent)
                conv = self.run_agent(identifier, mode='uml')
                self.assertEqual(conv['run']['status'], 'completed', conv['run'])
                docs = self.api('/api/explore/diagrams')['diagrams']
                self.assertEqual(len(docs), 2 * (('codex','opencode','dsh','claude','pi').index(agent)+1))
                self.assertEqual({d['type'] for d in docs}, {'activity','sequence'})
                self.assertTrue(any(m['kind']=='diagrams' for m in conv['history']['messages']))
                self.assertIsNone(conv['view'])
                doc = self.api('/api/explore/diagrams/'+docs[-1]['id'])
                self.assertEqual(doc['model']['nodes'][0]['evidence'][0]['path'], 'main.py')

    def test_native_failure_after_valid_batch_retains_draft_only(self):
        conv = self.run_agent(self.create(), mode='uml_failure')
        self.assertEqual(conv['run']['status'], 'failed')
        self.assertEqual(self.api('/api/explore/diagrams')['diagrams'], [])
        drafts = self.api('/api/explore/diagrams/drafts')['drafts']
        self.assertEqual(len(drafts),1)
        self.assertEqual(len(drafts[0]['diagrams']),2)

    def test_explicit_update_captures_new_source_and_checks_expected_revision(self):
        identifier = self.create()
        first = self.run_agent(identifier, mode='uml')
        doc = self.api('/api/explore/diagrams')['diagrams'][0]
        path = self.project/'main.py'
        path.write_text('# revised source\n'+path.read_text())
        with patch.dict(os.environ, {'STRATA_EXPLORATION_FIXTURE':'uml', 'STRATA_EXPLORATION_DIAGRAM':doc['id']}):
            self.api(f'/api/explore/conversations/{identifier}/messages', dict(text='根据当前代码更新', update=True, diagramId=doc['id'], expectedRevision=1))
            result = self.wait(identifier)
        self.assertEqual(result['run']['status'],'completed',result['run'])
        current = self.api('/api/explore/diagrams/'+doc['id'])
        old = self.api('/api/explore/diagrams/'+doc['id']+'?revision=1')
        self.assertEqual(current['revision'],2)
        self.assertNotEqual(current['snapshotId'],old['snapshotId'])
        with self.assertRaises(HTTPError) as caught:
            self.api(f'/api/explore/conversations/{identifier}/messages', dict(text='过期更新', update=True, diagramId=doc['id'], expectedRevision=1))
        self.assertEqual(caught.exception.code,409)
        caught.exception.close()
        # Current diagram is context, not an instruction to overwrite it.
        with patch.dict(os.environ, {'STRATA_EXPLORATION_FIXTURE':'uml'}):
            self.api(f'/api/explore/conversations/{identifier}/messages', dict(text='另画两张图', diagramId=doc['id'], expectedRevision=2))
            result=self.wait(identifier)
        self.assertEqual(result['run']['status'],'completed',result['run'])
        self.assertEqual(len(self.api('/api/explore/diagrams')['diagrams']),4)
        self.assertEqual(self.api('/api/explore/diagrams/'+doc['id'])['revision'],2)

    def test_cancellation_after_uml_draft_keeps_project_unpublished(self):
        identifier=self.create()
        with patch.dict(os.environ, {'STRATA_EXPLORATION_FIXTURE':'uml_hold'}):
            self.api(f'/api/explore/conversations/{identifier}/messages',dict(text='生成 UML'))
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                run=self.api('/api/explore/conversations/'+identifier)['run']
                if self.server.exploration.store.diagram_drafts(str(self.project)):
                    break
                with self.server.exploration.store.connect() as db:
                    pending=db.execute('SELECT 1 FROM diagram_drafts WHERE run_id=?',(run['id'],)).fetchone()
                if pending:break
                time.sleep(.03)
            self.assertTrue(pending)
            self.api(f'/api/explore/conversations/{identifier}/cancel',{})
            result=self.wait(identifier)
        self.assertEqual(result['run']['status'],'cancelled')
        self.assertEqual(self.api('/api/explore/diagrams')['diagrams'],[])
