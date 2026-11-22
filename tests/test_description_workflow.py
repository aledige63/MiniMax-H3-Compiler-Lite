import unittest
import copy
import json
from uuid import uuid4
from unittest.mock import patch
from app.repository import Repository
from app.api import create_app
from app.assistance import prune_picture_history
import test_m3 as m3


class DescriptionWorkflowTests(unittest.TestCase):
    setUp=m3.M3ApiTests.setUp
    tearDown=m3.M3ApiTests.tearDown
    view=m3.M3ApiTests.view
    command=m3.M3ApiTests.command
    save=m3.M3ApiTests.save
    picture=m3.M3ApiTests.picture
    trial=m3.M3ApiTests.trial
    run_job=m3.M3ApiTests.run_job
    completed=m3.M3ApiTests.completed
    apply=m3.M3ApiTests.apply

    def test_discard_persists_without_changing_draft_versions_media_or_cached_text(self):
        id,_=self.picture();self.trial()
        self.client.put(f'/api/cuts/{self.cut}/manual',json=self.command(text='Exact saved manual text.\n'))
        proposal=self.run_job('image_analyze',id);before=self.view();calls=self.fake.chat_calls
        command=self.command()
        response=self.client.post(f"/api/cuts/{self.cut}/assistance/{proposal['id']}/dismiss",json=command)
        self.assertEqual(response.status_code,200,response.text)
        after=response.json();job=next(j for j in after['assistance_jobs'] if j['id']==proposal['id'])
        self.assertTrue(job['discarded']);self.assertEqual(job['result'],proposal['result'])
        for key in ['draft_input','versions','manual_version_id','media_by_picture']:
            self.assertEqual(after[key],before[key],key)
        replay=self.client.post(f"/api/cuts/{self.cut}/assistance/{proposal['id']}/dismiss",json=command)
        self.assertEqual(replay.status_code,200,replay.text)
        self.assertEqual(self.view()['revision'],after['revision'])
        reopened=Repository(self.temp.name).workspace(self.cut)
        self.assertTrue(next(j for j in reopened.assistance_jobs if j['id']==proposal['id'])['discarded'])
        self.assertEqual(self.apply(proposal).status_code,422)
        self.assertEqual(self.fake.chat_calls,calls)

    def test_applying_marks_only_that_receipt_and_keeps_cache_available(self):
        id,_=self.picture();self.trial();proposal=self.run_job('image_analyze',id)
        result=self.apply(proposal);self.assertEqual(result.status_code,200,result.text)
        after=result.json();job=next(j for j in after['assistance_jobs'] if j['id']==proposal['id'])
        self.assertTrue(job['applied']);self.assertEqual(job['result'],proposal['result'])
        self.assertEqual(after['draft_input']['pictures'][0]['description_en'],proposal['result']['text'])
        self.assertFalse(after['draft_input']['pictures'][0]['confirmed'])
        cached=self.run_job('image_analyze',id)
        self.assertFalse(cached.get('applied',False));self.assertFalse(cached.get('discarded',False))
        self.assertEqual(cached['result']['metrics']['inference_calls'],0)

    def test_discard_cannot_hide_running_work_or_vision_trials(self):
        id,_=self.picture();trial=self.run_job('vision_trial')
        response=self.client.post(f"/api/cuts/{self.cut}/assistance/{trial['id']}/dismiss",json=self.command())
        self.assertEqual(response.status_code,422,response.text)
        self.fake.vision_entered.clear();self.fake.vision_release.clear()
        requested=self.client.post(f'/api/cuts/{self.cut}/assistance',json=self.command(kind='image_analyze',target_id=id,model='vision-test'))
        self.assertEqual(requested.status_code,202,requested.text)
        self.assertTrue(self.fake.vision_entered.wait(2))
        response=self.client.post(f"/api/cuts/{self.cut}/assistance/{requested.json()['id']}/dismiss",json=self.command())
        self.assertEqual(response.status_code,422,response.text)
        self.fake.vision_release.set()

    def test_discard_requires_the_current_cut_revision(self):
        id,_=self.picture();self.trial();proposal=self.run_job('image_analyze',id)
        command=self.command();command['expected_revision']-=1
        response=self.client.post(f"/api/cuts/{self.cut}/assistance/{proposal['id']}/dismiss",json=command)
        self.assertEqual(response.status_code,409,response.text)
        self.assertFalse(self.client.get('/api/assistance/jobs/'+proposal['id']).json().get('discarded',False))

    def test_discard_does_not_run_draft_or_library_synchronization(self):
        id,_=self.picture();self.trial();proposal=self.run_job('image_analyze',id);before=self.view()
        with patch.object(self.app.state.repository,'_sync_catalogue',side_effect=AssertionError('Discard must not synchronize drafts')):
            response=self.client.post(f"/api/cuts/{self.cut}/assistance/{proposal['id']}/dismiss",json=self.command())
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['draft_input'],before['draft_input'])

    def test_new_analyses_delete_older_receipts_and_orphan_cache_entries(self):
        id,_=self.picture();self.trial();jobs=[]
        for i in range(5):
            raw=self.view()['draft_input'];raw['pictures'][0]['analysis']={'attribute':f'detail {i}'};self.save(raw)
            jobs.append(self.run_job('image_analyze',id,force=True))
        after=self.view();images=[j for j in after['assistance_jobs'] if j['kind']=='image_analyze']
        self.assertEqual([j['id'] for j in images],[j['id'] for j in jobs[-3:]])
        for old in jobs[:2]:self.assertEqual(self.client.get('/api/assistance/jobs/'+old['id']).status_code,404)
        with self.app.state.repository.transaction() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM assistance_cache').fetchone()[0],3)
        self.assertEqual(after['draft_input']['pictures'][0]['description_en'],'manual description')

    def test_startup_limits_legacy_history_without_touching_draft_or_versions(self):
        id,_=self.picture();self.trial();proposal=self.run_job('image_analyze',id);before=self.view()
        with self.app.state.repository.transaction() as db:
            original=json.loads(db.execute('SELECT data FROM assistance_jobs WHERE id=?',(proposal['id'],)).fetchone()[0])
            for i in range(6):
                item=copy.deepcopy(original);item['id']=str(uuid4())
                db.execute('INSERT INTO assistance_jobs VALUES (?,?,?,?)',(item['id'],self.cut,item['kind'],json.dumps(item)))
        create_app(self.temp.name,self.fake)
        after=self.view()
        self.assertEqual(len([j for j in after['assistance_jobs'] if j['kind']=='image_analyze']),3)
        for key in ['draft_input','versions','media_by_picture']:self.assertEqual(after[key],before[key])

    def test_cleanup_keeps_live_work_and_cache_referenced_by_another_picture(self):
        id,_=self.picture();self.trial();proposal=self.run_job('image_analyze',id)
        with self.app.state.repository.transaction() as db:
            original=json.loads(db.execute('SELECT data FROM assistance_jobs WHERE id=?',(proposal['id'],)).fetchone()[0])
            pending=copy.deepcopy(original);pending.update(id=str(uuid4()),status='running',cache_key='pending-key')
            db.execute('INSERT INTO assistance_jobs VALUES (?,?,?,?)',(pending['id'],self.cut,pending['kind'],json.dumps(pending)))
            other=copy.deepcopy(original);other.update(id=str(uuid4()),target_id=str(uuid4()))
            db.execute('INSERT INTO assistance_jobs VALUES (?,?,?,?)',(other['id'],self.cut,other['kind'],json.dumps(other)))
            for i in range(5):
                item=copy.deepcopy(original);item.update(id=str(uuid4()),cache_key=f'new-{i}')
                db.execute('INSERT INTO assistance_jobs VALUES (?,?,?,?)',(item['id'],self.cut,item['kind'],json.dumps(item)))
            prune_picture_history(db,self.cut)
            self.assertIsNotNone(db.execute('SELECT id FROM assistance_jobs WHERE id=?',(pending['id'],)).fetchone())
            self.assertIsNotNone(db.execute('SELECT key FROM assistance_cache WHERE key=?',(original['cache_key'],)).fetchone())
