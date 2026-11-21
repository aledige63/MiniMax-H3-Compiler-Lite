import copy
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image

from app.api import create_app
from app.contracts import PurgeCommand
from app.domain import CurrentInterpretation
from app.exporting import ExportService
from app.repository import Repository
from test_api import FakeOllama

TEXT='subject_definitions:\nN/A\n\nsummary:\nAn empty room.\n\nretention_analysis:\nN/A\n\ndetailed_description:\n[Shot 1] An empty room.\n\noverall_soundscape:\nAmbient sounds.\n\nnon_diegetic_music:\nN/A'

def image_bytes(color):
    out=io.BytesIO();Image.new('RGB',(32,32),color).save(out,'PNG');return out.getvalue()

class M6Base(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.fake=FakeOllama();self.fake.plan=CurrentInterpretation(narrative_en='An empty room.',summary_en='An empty room.',estimated_duration_s=5.0,question=None)
        self.app=create_app(self.temp.name,self.fake);self.repo=self.app.state.repository
        self.client=TestClient(self.app,base_url='http://127.0.0.1:8767');self.client.__enter__()
        self.cut=self.client.get('/api/workspace').json()['id'];self.setup_cut()
    def tearDown(self):self.fake.release.set();self.client.__exit__(None,None,None);self.temp.cleanup()
    def view(self):return self.client.get(f'/api/cuts/{self.cut}').json()
    def cmd(self,**kw):return dict(command_id=str(uuid4()),expected_revision=self.view()['revision'],**kw)
    def save(self,raw):
        response=self.client.put(f'/api/cuts/{self.cut}/draft',json=self.cmd(input=raw));self.assertEqual(response.status_code,200,response.text);return response.json()
    def setup_cut(self):
        raw=self.view()['draft_input'];raw.update(request='Una stanza vuota.',declared_duration_s=5.0);self.save(raw)
    def project(self,id=None):
        id=id or self.view()['project_id'];return next(p for p in self.client.get('/api/projects').json() if p['id']==id)
    def manual(self,text=TEXT):
        response=self.client.put(f'/api/cuts/{self.cut}/manual',json=self.cmd(text=text,base_candidate_id=None));self.assertEqual(response.status_code,200,response.text);return response.json()['versions'][-1]
    def confirm(self,version):
        response=self.client.post(f'/api/cuts/{self.cut}/confirm',json=self.cmd(version_id=version['id'],acknowledge_reference_changes=True));self.assertEqual(response.status_code,200,response.text)
    def new_scene(self):
        p=self.project();scene=self.client.post(f'/api/projects/{p["id"]}/scenes',json=dict(command_id=str(uuid4()),expected_revision=p['revision'],name='Scena seguente')).json();self.cut=scene['cuts'][0]['id'];self.setup_cut();return scene
    def new_project(self,name='Altro progetto'):
        result=self.client.post('/api/projects',json=dict(command_id=str(uuid4()),expected_revision=0,name=name)).json();self.cut=result['scenes'][0]['cuts'][0]['id'];self.setup_cut();return result
    def picture(self,color='red'):
        view=self.client.post(f'/api/cuts/{self.cut}/items',json=self.cmd(kind='picture')).json();id=view['draft_input']['pictures'][-1]['id']
        media=self.client.post('/api/media',content=image_bytes(color),headers={'X-File-Name':'fixture.png'}).json()
        self.client.put(f'/api/cuts/{self.cut}/pictures/{id}/media',json=self.cmd(media_id=media['id']))
        raw=self.view()['draft_input'];raw['pictures'][-1].update(role='object',description_en='original red reference',confirmed=True,linked_to_h3=True);self.save(raw)
        return id,media
    def trash(self,scope,id):
        p=self.project(id) if scope=='project' else next(s for p in self.client.get('/api/projects').json() for s in p['scenes'] if s['id']==id)
        response=self.client.put(f'/api/{scope}s/{id}/trash',json=dict(command_id=str(uuid4()),expected_revision=p['revision'],trashed=True));self.assertEqual(response.status_code,200,response.text)
    def preview(self,scope='trash',id=None):
        selection=dict(scope=scope,**({'resource_id':id} if id else {}));response=self.client.post('/api/trash/preview',json=selection);self.assertEqual(response.status_code,200,response.text);return response.json()
    def purge_command(self,plan):return dict(command_id=str(uuid4()),selection=plan['selection'],plan_hash=plan['plan_hash'],confirmed=True,confirmation='ELIMINA')
    def purge(self,plan):return self.client.post('/api/trash/purge',json=self.purge_command(plan))
    def export(self,scope='cut',id=None,**kw):
        response=self.client.post('/api/exports',json=dict(scope=scope,resource_id=id or (self.cut if scope=='cut' else self.view()['scene_id'] if scope=='scene' else self.view()['project_id']),**kw));self.assertEqual(response.status_code,200,response.text);return response.json()

class ExportTests(M6Base):
    def test_single_cut_txt_is_exact_even_for_manual_text_and_old_version(self):
        first=self.manual(TEXT+'\n');self.confirm(first);self.manual(TEXT.replace('empty room','quiet street'))
        document=self.export(versions={self.cut:first['id']})
        downloaded=self.client.get(f'/api/exports/{document["id"]}/txt')
        self.assertEqual(downloaded.content,first['text'].encode());self.assertIn('attachment;',downloaded.headers['content-disposition']);self.assertEqual(self.fake.calls,0)
        self.assertEqual(self.client.get(f'/api/cuts/{self.cut}/text?version_id={first["id"]}').text,first['text'])

    def test_confirmed_and_latest_are_distinct_and_missing_cuts_remain_visible(self):
        first=self.manual();self.confirm(first);second=self.manual(TEXT+'\n')
        self.assertEqual(self.export()['items'][0]['version_id'],first['id'])
        self.assertEqual(self.export(policy='latest')['items'][0]['version_id'],second['id'])
        scene=self.view()['scene_id'];old=self.cut
        scene_data=next(s for s in self.project()['scenes'] if s['id']==scene)
        new=self.client.post(f'/api/scenes/{scene}/cuts',json=dict(command_id=str(uuid4()),expected_revision=scene_data['revision'],name='Vuoto')).json()
        document=self.export('scene',scene)
        self.assertEqual([i['cut_id'] for i in document['items']],[old,new['id']]);self.assertIsNone(document['items'][1]['text'])
        self.assertIn('Nessun prompt selezionato',self.client.get(f'/api/exports/{document["id"]}/txt').text)

    def test_project_is_ordered_and_excludes_trashed_scenes(self):
        self.confirm(self.manual());project=self.view()['project_id'];first_scene=self.view()['scene_id'];second=self.new_scene();self.confirm(self.manual())
        document=self.export('project',project);self.assertEqual([i['scene_number'] for i in document['items']],[1,2])
        self.trash('scene',first_scene);document=self.export('project',project);self.assertEqual([i['scene_number'] for i in document['items']],[2])

    def test_snapshot_notes_do_not_use_new_catalogue_and_prepared_export_does_not_change(self):
        self.picture();first=self.manual();document=self.export(policy='latest')
        raw=self.view()['draft_input'];raw['pictures'][0]['description_en']='new blue description';self.save(raw);self.manual(TEXT+'\n')
        retained=self.client.get(f'/api/exports/{document["id"]}/print').text
        self.assertIn('original red reference',retained);self.assertNotIn('new blue description',retained)
        self.assertEqual(self.client.get(f'/api/exports/{document["id"]}/txt').text,first['text'])

    def test_print_html_escapes_untrusted_text_and_has_all_cuts_expanded(self):
        self.manual(TEXT+'\n<script>alert("private")</script>');first=self.cut;scene=self.view()['scene_id'];s=next(s for s in self.project()['scenes'] if s['id']==scene)
        self.cut=self.client.post(f'/api/scenes/{scene}/cuts',json=dict(command_id=str(uuid4()),expected_revision=s['revision'],name='Secondo')).json()['id'];self.setup_cut();self.manual()
        document=self.export('scene',scene,policy='latest');response=self.client.get(f'/api/exports/{document["id"]}/print')
        self.assertEqual(response.text.count('<article>'),2);self.assertEqual(response.text.count('<pre>'),2);self.assertIn('&lt;script&gt;',response.text);self.assertNotIn('<script>alert',response.text)
        self.assertIn("default-src 'none'",response.headers['content-security-policy']);self.assertNotIn('<details',response.text)

    def test_wrong_version_scope_and_expiration_are_explicit(self):
        version=self.manual();first=self.cut;self.new_project();self.manual()
        response=self.client.post('/api/exports',json=dict(scope='cut',resource_id=self.cut,versions={self.cut:version['id']}));self.assertEqual(response.status_code,422)
        response=self.client.post('/api/exports',json=dict(scope='cut',resource_id=self.cut,versions={first:version['id']}));self.assertEqual(response.status_code,422)
        document=self.export(policy='latest');service=self.app.state.exports
        created,data=service.documents[document['id']];service.documents[document['id']]=(created-1801,data)
        self.assertEqual(self.client.get(f'/api/exports/{document["id"]}/txt').status_code,404);self.assertEqual(self.fake.calls,0)

    def test_historical_snapshot_absent_stays_unknown(self):
        version=self.manual()
        with self.repo.transaction() as db:
            raw=json.loads(db.execute('SELECT data FROM versions WHERE id=?',(version['id'],)).fetchone()[0]);raw['input_snapshot']=None
            db.execute('UPDATE versions SET data=? WHERE id=?',(json.dumps(raw),version['id']))
        item=self.export(policy='latest')['items'][0];self.assertFalse(item['snapshot_known']);self.assertIn('non disponibile',item['references'][0])

class PurgeTests(M6Base):
    def new_cut(self, **extra):
        scene_id = self.view()['scene_id']
        scene = next(scene for scene in self.project()['scenes'] if scene['id'] == scene_id)
        response = self.client.post(f'/api/scenes/{scene_id}/cuts', json={
            'command_id': str(uuid4()), 'expected_revision': scene['revision'], 'name': 'Altro cut', **extra,
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.cut = response.json()['id']
        return response.json()

    def test_cut_trash_restore_and_purge_keep_the_scene_and_its_picture(self):
        first = self.cut
        _, media = self.picture()
        self.confirm(self.manual())
        scene_id = self.view()['scene_id']
        self.new_cut(inherit_references=True)
        second = self.cut
        self.setup_cut()
        saved = self.manual(TEXT + '\n')
        document = self.export(policy='latest')
        path = f'/api/cuts/{second}'
        move = self.cmd(trashed=True)
        archived = self.client.put(path + '/trash', json=move)
        self.assertEqual(archived.status_code, 200, archived.text)
        self.assertEqual(self.client.put(path + '/trash', json=move).json(), archived.json())
        self.assertEqual([cut['id'] for cut in archived.json()['cuts']], [first])
        archived_cut = archived.json()['trashed_cuts'][0]
        self.assertEqual(archived_cut['id'], second)
        self.assertEqual(self.client.get(path).json()['detail']['code'], 'cut_trashed')
        self.assertEqual([item['cut_id'] for item in self.export('scene', scene_id)['items']], [first])

        self.cut = first
        self.assertEqual(self.client.put(f'/api/cuts/{first}/trash', json=self.cmd(trashed=True)).json()['detail']['code'], 'last_cut')
        third = self.new_cut(inherit_references=True)
        self.assertEqual(third['number'], 3)
        self.assertEqual(third['previous_cut']['id'], first)
        restored = self.client.put(path + '/trash', json={
            'command_id': str(uuid4()), 'expected_revision': archived_cut['revision'], 'trashed': False,
        })
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(self.client.get(path).json()['versions'][-1], saved)

        self.cut = second
        self.assertEqual(self.client.put(path + '/trash', json=self.cmd(trashed=True)).status_code, 200)
        plan = self.preview('cut', second)
        self.assertEqual((plan['cuts'], plan['versions'], plan['files_to_remove']), (1, 1, 0))
        self.assertEqual(self.preview()['cuts'], 1)
        purged = self.purge(plan)
        self.assertEqual(purged.status_code, 200, purged.text)
        self.assertEqual(self.client.get(path).json()['detail']['code'], 'not_found')
        self.assertEqual(self.client.get('/api/media/' + media['id']).status_code, 200)
        self.assertEqual(self.client.get(f'/api/exports/{document["id"]}/txt').status_code, 404)
        self.assertEqual(self.fake.calls, 0)

    def test_purge_of_trashed_cut_is_blocked_by_an_explicit_continuity_source(self):
        first = self.cut
        version = self.manual()
        self.new_cut()
        raw = self.view()['draft_input']
        raw['continuity'] = dict(mode='latent', declared_state='La stanza è vuota.',
                                 previous_cut_id=first, previous_version_id=version['id'])
        dependent = self.save(raw)['id']
        self.cut = first
        archived = self.client.put(f'/api/cuts/{first}/trash', json=self.cmd(trashed=True))
        self.assertEqual(archived.status_code, 200, archived.text)
        self.cut = dependent
        self.assertEqual(self.view()['previous_cut']['version']['id'], version['id'])
        plan = self.preview('cut', first)
        self.assertTrue(plan['blockers'])
        self.assertEqual(self.purge(plan).json()['detail']['code'], 'purge_blocked')

    def test_only_trashed_items_with_fresh_plan_and_explicit_consent_can_be_removed(self):
        project=self.view()['project_id'];self.assertEqual(self.client.post('/api/trash/preview',json=dict(scope='project',resource_id=project)).status_code,409)
        self.trash('project',project);plan=self.preview();command=self.purge_command(plan)
        for patch_value in [dict(confirmed=False),dict(confirmation='NO')]:
            self.assertEqual(self.client.post('/api/trash/purge',json=command|patch_value).status_code,422)
        self.new_project();self.assertEqual(self.client.post('/api/trash/purge',json=command).status_code,409)
        self.assertTrue(self.project(project)['trashed'])

    def test_project_purge_removes_unshared_files_idempotently_and_invalidates_export(self):
        self.picture();self.confirm(self.manual());project=self.view()['project_id'];document=self.export()
        with closing(self.repo.connect()) as db:path=Path(self.temp.name)/db.execute('SELECT relative_path FROM media').fetchone()[0]
        self.trash('project',project);plan=self.preview();self.assertEqual(plan['files_to_remove'],1);self.assertFalse(plan['blockers'])
        command=self.purge_command(plan);response=self.client.post('/api/trash/purge',json=command);self.assertEqual(response.status_code,200,response.text)
        self.assertFalse(path.exists());self.assertEqual(self.client.post('/api/trash/purge',json=command).json(),response.json())
        self.assertEqual(self.client.get('/api/projects').json(),[]);self.assertEqual(self.client.get('/api/workspace').status_code,404)
        self.assertEqual(self.client.get(f'/api/exports/{document["id"]}/txt').status_code,404)
        self.new_project();self.assertEqual(self.client.get('/api/workspace').status_code,200);self.assertEqual(self.fake.calls,0)

    def test_shared_file_in_another_project_is_retained(self):
        _,media=self.picture();self.manual();first=self.view()['project_id'];self.new_project();_,shared=self.picture();self.assertEqual(media['id'],shared['id'])
        self.trash('project',first);plan=self.preview();self.assertEqual(plan['files_to_remove'],0);self.assertEqual(plan['media_retained'],1)
        self.assertEqual(self.purge(plan).status_code,200);self.assertEqual(self.client.get('/api/media/'+shared['id']).status_code,200)

    def test_deleting_scene_keeps_project_library_and_other_trash(self):
        _,media=self.picture();self.manual();scene=self.view()['scene_id'];project=self.view()['project_id'];self.new_scene();self.manual()
        self.trash('scene',scene);plan=self.preview('scene',scene);self.assertEqual(plan['media_retained'],1);self.assertEqual(self.purge(plan).status_code,200)
        self.assertEqual(self.client.get('/api/media/'+media['id']).status_code,200);self.assertEqual(len(self.project(project)['scenes']),1)

    def test_old_version_snapshot_protects_replaced_file(self):
        _,media=self.picture();self.manual();first_project=self.view()['project_id'];self.new_project();id,_=self.picture();self.manual()
        fresh=self.client.post('/api/media',content=image_bytes('blue')).json()
        self.client.put(f'/api/cuts/{self.cut}/pictures/{id}/media',json=self.cmd(media_id=fresh['id']))
        self.trash('project',first_project);plan=self.preview();self.assertEqual(plan['media_retained'],1)
        self.assertEqual(self.purge(plan).status_code,200);self.assertEqual(self.client.get('/api/media/'+media['id']).status_code,200)

    def test_unknown_historical_snapshot_conservatively_preserves_media(self):
        self.picture();first=self.view()['project_id'];self.new_project();version=self.manual()
        with self.repo.transaction() as db:
            saved=json.loads(db.execute('SELECT data FROM versions WHERE id=?',(version['id'],)).fetchone()[0]);saved['input_snapshot']=None;db.execute('UPDATE versions SET data=? WHERE id=?',(json.dumps(saved),version['id']))
        self.trash('project',first);plan=self.preview();self.assertTrue(plan['warnings']);self.assertEqual(plan['files_to_remove'],0)

    def test_remaining_draft_dependency_blocks_source_scene_purge(self):
        version=self.manual();scene=self.view()['scene_id'];old=self.cut;self.new_scene();raw=self.view()['draft_input']
        # Archivio storico con un collegamento che l'editor corrente rifiuta:
        # non deve diventare un'autorizzazione a cancellarne la sorgente.
        with self.repo.transaction() as db:
            state=json.loads(db.execute('SELECT data FROM cuts WHERE id=?',(self.cut,)).fetchone()[0])
            state['draft_input']['continuity']=dict(mode='latent',declared_state='Stato.',previous_cut_id=old,previous_version_id=version['id'])
            db.execute('UPDATE cuts SET data=? WHERE id=?',(json.dumps(state),self.cut))
        self.trash('scene',scene);plan=self.preview('scene',scene);self.assertTrue(plan['blockers']);self.assertEqual(self.purge(plan).status_code,409)

    def test_running_or_cancelled_inflight_inference_blocks_purge(self):
        self.fake.release.clear();view=self.view()
        response=self.client.post(f'/api/cuts/{self.cut}/compile',json=self.cmd(cut_id=self.cut,input=view['draft_input'],model='local-test'));self.assertEqual(response.status_code,202)
        self.assertTrue(self.fake.entered.wait(2));id=response.json()['id']
        self.client.post('/api/jobs/'+id+'/cancel',json=self.cmd());project=self.view()['project_id'];self.trash('project',project)
        plan=self.preview();self.assertTrue(plan['blockers']);self.assertEqual(self.purge(plan).status_code,409)
        self.fake.release.set();self.app.state.worker.pending.join();self.assertEqual(self.purge(self.preview()).status_code,200)

    def test_symlink_never_deletes_external_file_and_pending_cleanup_can_resume(self):
        _,media=self.picture();self.manual();project=self.view()['project_id']
        with closing(self.repo.connect()) as db:relative=db.execute('SELECT relative_path FROM media WHERE id=?',(media['id'],)).fetchone()[0]
        managed=Path(self.temp.name)/relative
        with tempfile.TemporaryDirectory() as external:
            original=Path(external)/'original.png';original.write_bytes(managed.read_bytes());managed.unlink()
            try:
                managed.symlink_to(original)
            except OSError as error:
                if getattr(error, 'winerror', None) == 1314:
                    self.skipTest('Windows account cannot create symbolic links')
                raise
            self.trash('project',project);response=self.purge(self.preview());self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['pending_files'],1);self.assertTrue(original.is_file())
            managed.unlink();managed.write_bytes(original.read_bytes());Repository(self.temp.name)
            self.assertFalse(managed.exists());self.assertTrue(original.is_file())

    @unittest.skipUnless(sys.platform == 'win32', 'Windows junctions')
    def test_junction_never_deletes_external_media(self):
        self.picture()
        self.manual()
        with closing(self.repo.connect()) as db:
            managed = Path(self.temp.name) / db.execute('SELECT relative_path FROM media').fetchone()[0]
        original_folder = managed.parent.with_name('original-media')
        with tempfile.TemporaryDirectory() as external:
            external_file = Path(external) / managed.name
            external_file.write_bytes(managed.read_bytes())
            managed.parent.rename(original_folder)
            junction = subprocess.run(
                ['cmd.exe', '/d', '/c', 'mklink', '/J', str(managed.parent), external],
                capture_output=True,
            )
            self.assertEqual(junction.returncode, 0, junction.stderr)
            try:
                self.trash('project', self.view()['project_id'])
                response = self.purge(self.preview())
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()['pending_files'], 1)
                self.assertTrue(external_file.is_file())
            finally:
                managed.parent.rmdir()
                original_folder.rename(managed.parent)
            self.repo.cleanup_files()
            self.assertFalse(managed.exists())
            self.assertTrue(external_file.is_file())

    def test_database_failure_rolls_back_before_any_file_is_deleted(self):
        self.picture();self.manual();project=self.view()['project_id'];self.trash('project',project);plan=self.preview()
        with closing(self.repo.connect()) as db:
            path=Path(self.temp.name)/db.execute('SELECT relative_path FROM media').fetchone()[0]
            db.execute("CREATE TRIGGER reject_purge BEFORE INSERT ON commands WHEN NEW.operation='purge' BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.repo.purge(PurgeCommand.model_validate_json(json.dumps(self.purge_command(plan))))
        self.assertTrue(path.is_file());self.assertTrue(self.project(project)['trashed'])
        with closing(self.repo.connect()) as db:self.assertEqual(db.execute('SELECT count(*) FROM pending_file_deletions').fetchone()[0],0)

    def test_migration_4_to_5_backs_up_and_preserves_all_existing_rows(self):
        self.manual()
        with closing(self.repo.connect()) as db:
            db.execute("UPDATE settings SET value='4' WHERE key='schema_version'");db.execute('DROP TABLE pending_file_deletions')
            before=list(db.execute('SELECT data FROM versions'));before=[r[0] for r in before]
        Repository(self.temp.name)
        with closing(sqlite3.connect(Path(self.temp.name)/'workspace.before-m6.sqlite3')) as db:self.assertEqual(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0],'4')
        with closing(self.repo.connect()) as db:
            self.assertEqual(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0],'8');self.assertEqual([r[0] for r in db.execute('SELECT data FROM versions')],before)

    def test_audio_video_and_image_proxy_files_are_collected_only_with_their_project(self):
        from test_m3 import wav
        from test_m4 import video_bytes
        picture,original=self.picture()
        proxy=self.client.post('/api/media',content=image_bytes('blue')).json()
        self.client.put(f'/api/cuts/{self.cut}/pictures/{picture}/proxy',json=self.cmd(media_id=proxy['id']))
        audio=self.client.post('/api/audio-media',content=wav()).json();video=self.client.post('/api/video-media',content=video_bytes()).json()
        for kind,media in [('audio',audio),('video',video)]:
            view=self.client.post(f'/api/cuts/{self.cut}/items',json=self.cmd(kind=kind)).json()
            key='audio_references' if kind=='audio' else 'videos';id=view['draft_input'][key][-1]['id']
            plural='audio' if kind=='audio' else 'videos'
            response=self.client.put(f'/api/cuts/{self.cut}/{plural}/{id}/media',json=self.cmd(media_id=media['id']));self.assertEqual(response.status_code,200,response.text)
        project=self.view()['project_id'];self.trash('project',project);plan=self.preview()
        self.assertEqual(plan['files_to_remove'],7);response=self.purge(plan);self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['pending_files'],0)
        for folder in ['media','audio','video']:self.assertEqual(list((Path(self.temp.name)/folder).iterdir()),[])

    def test_other_trash_and_reuploaded_live_paths_remain_protected(self):
        _,media=self.picture();first=self.view()['project_id'];self.new_project();self.picture();second=self.view()['project_id']
        self.trash('project',first);self.trash('project',second)
        plan=self.preview('project',first);self.assertEqual(plan['files_to_remove'],0);self.assertEqual(self.purge(plan).status_code,200)
        with self.repo.transaction() as db:
            row=db.execute('SELECT relative_path,sha256 FROM media WHERE id=?',(media['id'],)).fetchone();db.execute('INSERT INTO pending_file_deletions VALUES (?,?)',tuple(row))
        self.repo.cleanup_files();self.assertTrue((Path(self.temp.name)/row['relative_path']).is_file())
        with closing(self.repo.connect()) as db:self.assertEqual(db.execute('SELECT count(*) FROM pending_file_deletions').fetchone()[0],0)

class M6AccessTests(unittest.TestCase):
    def test_exports_print_and_purge_require_lan_authentication_and_csrf(self):
        from app.access import Access
        with tempfile.TemporaryDirectory() as folder:
            repo=Repository(folder);Access(repo).set_password('synthetic-password-for-tests')
            app=create_app(folder,FakeOllama(),lan=True,allowed_hosts=['workstation.local'])
            with TestClient(app,base_url='http://workstation.local:8767',client=('10.0.0.40',5000)) as c:
                for path in ['/api/exports/missing/txt','/api/exports/missing/print']:
                    self.assertEqual(c.get(path).status_code,401)
                self.assertEqual(c.post('/api/trash/purge',json={}).status_code,401)
                csrf=c.post('/api/access/login',json={'password':'synthetic-password-for-tests'}).json()['csrf']
                self.assertEqual(c.post('/api/exports',json={}).status_code,403)
                self.assertEqual(c.post('/api/trash/preview',json=dict(scope='trash')).status_code,403)
                self.assertEqual(c.post('/api/trash/preview',json=dict(scope='trash'),headers={'X-CSRF-Token':csrf}).status_code,200)
                self.assertEqual(c.post('/api/trash/purge',json={},headers={'X-CSRF-Token':csrf,'Origin':'http://evil.test'}).status_code,403)
                cut=c.get('/api/workspace').json()['id']
                doc=c.post('/api/exports',json=dict(scope='cut',resource_id=cut),headers={'X-CSRF-Token':csrf}).json()
                self.assertEqual(c.get('/api/exports/'+doc['id']+'/print').status_code,200)
