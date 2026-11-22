import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image

from app.access import Access
from app.api import create_app
from app.contracts import DraftCommand
from app.repository import Repository
import test_api as m1
from test_api import FakeOllama
from test_repository import legacy_archive


def png(color='purple'):
    buffer = io.BytesIO()
    Image.new('RGB', (12, 8), color).save(buffer, format='PNG')
    return buffer.getvalue()


class M2Tests(unittest.TestCase):
    setUp = m1.ApiTests.setUp
    tearDown = m1.ApiTests.tearDown
    command = m1.ApiTests.command
    prepare = m1.ApiTests.prepare
    compile = m1.ApiTests.compile
    completed = m1.ApiTests.completed
    def create_cut(self, new_scene=False):
        project = self.client.get('/api/projects').json()[0]
        if new_scene:
            response = self.client.post(f"/api/projects/{project['id']}/scenes", json={
                'command_id': str(uuid4()), 'expected_revision': project['revision'], 'name': 'Seconda scena'})
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()['cuts'][0]['id']
        scene = project['scenes'][0]
        response = self.client.post(f"/api/scenes/{scene['id']}/cuts", json={
            'command_id': str(uuid4()), 'expected_revision': scene['revision'], 'name': 'Secondo cut'})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['id']

    def cut_command(self, cut_id, **extra):
        current = self.client.get(f'/api/cuts/{cut_id}').json()
        return {'command_id': str(uuid4()), 'expected_revision': current['revision'], **extra}

    def test_project_scene_cut_hierarchy_and_independent_browser_selection(self):
        self.prepare()
        second = self.create_cut(new_scene=True)
        blank = self.client.get(f'/api/cuts/{second}').json()
        self.assertEqual(blank['number'], 1)
        self.assertEqual(blank['draft_input']['dialogues'], [])
        self.assertEqual(blank['draft_input']['active_units'], [])
        self.assertNotEqual(blank['scene_id'], self.client.get('/api/workspace').json()['scene_id'])
        self.assertEqual(self.client.get('/api/workspace').json()['id'], self.cut)
        self.assertEqual(self.fake.calls, 0)

    def test_deleted_dialogue_number_is_reused_without_changing_saved_versions(self):
        self.prepare()
        path = f'/api/cuts/{self.cut}'
        manual = self.client.put(path + '/manual', json=self.command(text='Testo conservato.')).json()['versions'][-1]
        added = self.client.post(path + '/items', json=self.command(kind='dialogue')).json()
        self.assertEqual(added['draft_input']['dialogues'][-1]['id'], 'd2')
        raw = added['draft_input']
        raw['dialogues'] = [dialogue for dialogue in raw['dialogues'] if dialogue['id'] != 'd1']
        saved = self.client.put(path + '/draft', json=self.command(input=raw))
        self.assertEqual(saved.status_code, 200, saved.text)
        command = self.command(kind='dialogue')
        recreated = self.client.post(path + '/items', json=command)
        self.assertEqual(recreated.status_code, 200, recreated.text)
        self.assertEqual([dialogue['id'] for dialogue in recreated.json()['draft_input']['dialogues']], ['d2', 'd1'])
        self.assertEqual(self.client.post(path + '/items', json=command).json(), recreated.json())
        self.assertEqual(recreated.json()['versions'][-1], manual)
        self.assertEqual(self.client.post(path + '/items', json=self.command(kind='dialogue')).json()['draft_input']['dialogues'][-1]['id'], 'd3')
        self.assertEqual(self.fake.calls, 0)

    def test_new_cut_can_inherit_the_previous_draft_references_without_reimporting_media(self):
        self.prepare()
        path = f'/api/cuts/{self.cut}'
        picture_id = self.input['pictures'][0]['id']
        media = self.client.post('/api/media', content=png(), headers={'X-File-Name': 'Anna.png'}).json()
        attached = self.client.put(f'{path}/pictures/{picture_id}/media', json=self.command(media_id=media['id']))
        self.assertEqual(attached.status_code, 200, attached.text)
        for kind in ('audio', 'video', 'picture'):
            added = self.client.post(f'{path}/items', json=self.command(kind=kind))
            self.assertEqual(added.status_code, 200, added.text)
        raw = added.json()['draft_input']
        raw['pictures'][0].update(confirmed=True, linked_to_h3=True)
        raw['pictures'][-1].update(role='style', description_en='Soft indoor light', confirmed=True,
                                   linked_to_h3=True, guidance={'enabled': True})
        raw['active_units'][1]['sources'].append({'origin': 'context', 'attribute': 'appearance'})
        raw['continuity'] = {'mode': 'latent', 'declared_state': 'Marco è già nella stanza.', 'external_source': 'Clip'}
        saved = self.client.put(f'{path}/draft', json=self.command(input=raw))
        self.assertEqual(saved.status_code, 200, saved.text)
        original = saved.json()
        scene_path = f"/api/scenes/{original['scene_id']}/cuts"
        scene = self.client.get('/api/projects').json()[0]['scenes'][0]
        command = dict(command_id=str(uuid4()), expected_revision=scene['revision'], name='Segue', inherit_references=True)
        created = self.client.post(scene_path, json=command)
        self.assertEqual(created.status_code, 200, created.text)
        new = created.json()
        self.assertEqual(self.client.post(scene_path, json=command).json(), new)

        draft = new['draft_input']
        self.assertEqual(draft['pictures'][0], original['draft_input']['pictures'][0] | {'linked_to_h3': False})
        self.assertEqual(new['media_by_picture'][picture_id], original['media_by_picture'][picture_id])
        self.assertEqual(new['unit_ids'], original['unit_ids'])
        self.assertEqual(draft['active_units'][0], original['draft_input']['active_units'][0])
        self.assertEqual(draft['active_units'][1], raw['active_units'][1] | {
            'sources': raw['active_units'][1]['sources'][:-1], 'confirmed': False})
        self.assertFalse(draft['pictures'][-1]['confirmed'])
        self.assertNotIn('guidance', draft['pictures'][-1])
        self.assertEqual(draft['request'], '')
        self.assertEqual(draft['continuity']['mode'], 'none')
        for key in ('dialogues', 'audio_references', 'videos'):
            self.assertEqual(draft.get(key, []), [])
        self.assertEqual(new['versions'], [])

        new_path = f"/api/cuts/{new['id']}"
        draft['pictures'][0]['slot'] = 9
        edited = self.client.put(f'{new_path}/draft', json=self.cut_command(new['id'], input=draft))
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(self.client.get(path).json()['draft_input'], original['draft_input'])
        third = self.client.post(scene_path, json=command | {
            'command_id': str(uuid4()), 'expected_revision': scene['revision'] + 1}).json()
        self.assertEqual(third['draft_input']['pictures'][0]['slot'], 9)
        blank = self.client.post(scene_path, json=command | {
            'command_id': str(uuid4()), 'expected_revision': scene['revision'] + 2, 'inherit_references': False}).json()
        self.assertEqual(blank['draft_input']['pictures'], [])
        self.assertEqual(blank['draft_input']['active_units'], [])
        self.assertEqual(self.fake.calls, 0)

    def test_project_subject_allocator_and_reuse_with_distinct_picture_slots(self):
        self.prepare()
        first = self.client.get('/api/workspace').json()
        second = self.create_cut()
        added = self.client.post(f'/api/cuts/{second}/items', json=self.cut_command(second, kind='unit')).json()
        self.assertEqual(added['draft_input']['active_units'][0]['subject'], 4)
        subject_id = first['unit_ids']['1']
        pictures = self.input['pictures']
        slots = {pictures[0]['id']: 7, pictures[1]['id']: 9}
        response = self.client.post(f'/api/cuts/{second}/reuse', json=self.cut_command(second, kind='unit', reference_id=subject_id, slots=slots))
        self.assertEqual(response.status_code, 200, response.text)
        reused = response.json()
        self.assertEqual(reused['unit_ids']['1'], subject_id)
        self.assertEqual([p['slot'] for p in reused['draft_input']['pictures']], [7, 9])
        self.assertTrue(all(not p['linked_to_h3'] for p in reused['draft_input']['pictures']))
        self.assertEqual(self.client.get(f'/api/cuts/{self.cut}').json()['draft_input'], first['draft_input'])
        self.assertEqual(self.fake.calls, 0)

    def test_library_can_exceed_nine_but_each_cut_cannot(self):
        for _ in range(9):
            response = self.client.post(f'/api/cuts/{self.cut}/items', json=self.command(kind='picture'))
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.post(f'/api/cuts/{self.cut}/items', json=self.command(kind='picture')).status_code, 422)
        second = self.create_cut()
        for _ in range(3):
            self.assertEqual(self.client.post(f'/api/cuts/{second}/items', json=self.cut_command(second, kind='picture')).status_code, 200)
        project_id = self.client.get('/api/workspace').json()['project_id']
        self.assertEqual(len(self.client.get(f'/api/projects/{project_id}/library').json()['pictures']), 12)
        self.assertEqual(self.fake.calls, 0)

    def test_restored_local_provisional_subject_cannot_replace_reallocated_identity(self):
        old = self.client.post(f'/api/cuts/{self.cut}/items', json=self.command(kind='unit')).json()
        old_id = old['unit_ids']['1']
        empty = {'request': '', 'active_units': [], 'pictures': [], 'dialogues': []}
        self.client.put(f'/api/cuts/{self.cut}/draft', json=self.command(input=empty))
        second = self.create_cut()
        new = self.client.post(f'/api/cuts/{second}/items', json=self.cut_command(second, kind='unit')).json()
        self.assertEqual(new['draft_input']['active_units'][0]['subject'], 1)
        self.assertNotEqual(new['unit_ids']['1'], old_id)
        restored = self.client.put(f'/api/cuts/{self.cut}/draft', json=self.command(input=old['draft_input']))
        self.assertEqual(restored.status_code, 409)
        self.assertEqual(restored.json()['detail']['code'], 'reference_conflict')
        self.assertEqual(self.client.get(f'/api/cuts/{self.cut}').json()['draft_input'], empty)

    def test_reuse_rejects_foreign_project_and_duplicate_slots(self):
        self.prepare()
        current = self.client.get('/api/workspace').json()
        second = self.create_cut()
        bad = self.client.post(f'/api/cuts/{second}/reuse', json=self.cut_command(second, kind='unit', reference_id=current['unit_ids']['1'],
                              slots={p['id']: 1 for p in self.input['pictures']}))
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(self.client.get(f'/api/cuts/{second}').json()['draft_input']['pictures'], [])
        other = self.client.post('/api/projects', json={'command_id': str(uuid4()), 'expected_revision': 0, 'name': 'Altro'}).json()['scenes'][0]['cuts'][0]['id']
        bad = self.client.post(f'/api/cuts/{other}/reuse', json=self.cut_command(other, kind='picture', reference_id=self.input['pictures'][0]['id'], slots={self.input['pictures'][0]['id']: 1}))
        self.assertEqual(bad.status_code, 404)

    def test_confirmation_is_specific_and_remains_after_new_draft(self):
        self.prepare()
        job, _ = self.compile(); completed = self.completed(job)
        command = self.command(version_id=completed['candidate_id'])
        response = self.client.post(f'/api/cuts/{self.cut}/confirm', json=command)
        self.assertEqual(response.status_code, 200, response.text)
        approved = response.json()
        self.assertEqual(self.client.post(f'/api/cuts/{self.cut}/confirm', json=command).json(), approved)
        self.assertEqual(approved['state'], 'confirmed')
        self.assertTrue(approved['versions'][-1]['user_approved'])
        text = approved['versions'][-1]['text']
        raw = approved['draft_input']; raw['request'] += ' Poi si ferma.'
        edited = self.client.put(f'/api/cuts/{self.cut}/draft', json=self.command(input=raw)).json()
        self.assertEqual(edited['confirmed_version_id'], completed['candidate_id'])
        self.assertEqual(edited['versions'][-1]['text'], text)
        self.assertEqual(edited['state'], 'draft')
        self.assertEqual(self.fake.calls, 1)

    def test_manual_changed_bindings_require_explicit_reconciliation(self):
        self.prepare(); job, _ = self.compile(); done = self.completed(job)
        view = self.client.get('/api/workspace').json(); generated = view['versions'][-1]
        raw = view['draft_input']; raw['pictures'][0]['slot'], raw['pictures'][2]['slot'] = 3, 1
        self.client.put(f'/api/cuts/{self.cut}/draft', json=self.command(input=raw))
        manual = self.client.put(f'/api/cuts/{self.cut}/manual', json=self.command(text=generated['text'], base_candidate_id=done['candidate_id'])).json()['versions'][-1]
        command = self.command(version_id=manual['id'])
        blocked = self.client.post(f'/api/cuts/{self.cut}/confirm', json=command)
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertEqual(blocked.json()['detail']['code'], 'reference_reconciliation_required')
        command['acknowledge_reference_changes'] = True
        confirmed = self.client.post(f'/api/cuts/{self.cut}/confirm', json=command)
        self.assertEqual(confirmed.status_code, 200, confirmed.text)

    def test_invalid_manual_cannot_be_confirmed_but_stays_copyable(self):
        manual = self.client.put(f'/api/cuts/{self.cut}/manual', json=self.command(text='  Bozza non valida.\n')).json()['versions'][-1]
        response = self.client.post(f'/api/cuts/{self.cut}/confirm', json=self.command(version_id=manual['id']))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get(f"/api/cuts/{self.cut}/text?version_id={manual['id']}").text, manual['text'])
        self.assertEqual(self.fake.calls, 0)

    def test_finalize_requires_current_confirmations_and_reopen_allows_edits(self):
        project = self.client.get('/api/projects').json()[0]; scene = project['scenes'][0]
        final = {'command_id': str(uuid4()), 'expected_revision': scene['revision'], 'finalized': True}
        self.assertEqual(self.client.put(f"/api/scenes/{scene['id']}/finalize", json=final).status_code, 409)
        self.prepare(); job, _ = self.compile(); done = self.completed(job)
        self.client.post(f'/api/cuts/{self.cut}/confirm', json=self.command(version_id=done['candidate_id']))
        final = self.client.put(f"/api/scenes/{scene['id']}/finalize", json=final)
        self.assertEqual(final.status_code, 200, final.text)
        self.assertEqual(self.client.put(f'/api/cuts/{self.cut}/draft', json=self.command(input=self.input)).status_code, 409)
        self.assertEqual(self.client.post(f"/api/scenes/{scene['id']}/cuts", json={'command_id': str(uuid4()), 'expected_revision': final.json()['revision'], 'name': 'Nuovo'}).status_code, 409)
        reopened = self.client.put(f"/api/scenes/{scene['id']}/finalize", json={'command_id': str(uuid4()), 'expected_revision': final.json()['revision'], 'finalized': False})
        self.assertEqual(reopened.status_code, 200)
        self.assertEqual(self.client.put(f'/api/cuts/{self.cut}/draft', json=self.command(input=self.input)).status_code, 200)

    def test_real_image_upload_dedup_preview_snapshot_and_missing_file(self):
        self.prepare(); content = png()
        first = self.client.post('/api/media', content=content, headers={'X-File-Name': '..%2Fphoto.jpg', 'Content-Type': 'image/jpeg'})
        self.assertEqual(first.status_code, 200, first.text)
        media = first.json()
        self.assertEqual(media['content_type'], 'image/png')
        self.assertEqual(media['display_name'], 'photo.jpg')
        self.assertEqual(media['sha256'], hashlib.sha256(content).hexdigest())
        self.assertEqual((media['width'], media['height']), (12, 8))
        repeated = self.client.post('/api/media', content=content).json()
        self.assertEqual(repeated['id'], media['id'])
        self.assertEqual(self.client.get(f"/api/media/{media['id']}").content, content)
        picture_id = self.input['pictures'][0]['id']
        attached = self.client.put(f'/api/cuts/{self.cut}/pictures/{picture_id}/media', json=self.command(media_id=media['id']))
        self.assertEqual(attached.status_code, 200, attached.text)
        self.assertFalse(attached.json()['draft_input']['pictures'][0]['confirmed'])
        self.input = attached.json()['draft_input']
        self.input['pictures'][0].update(confirmed=True, linked_to_h3=True)
        self.client.put(f'/api/cuts/{self.cut}/draft', json=self.command(input=self.input))
        job, _ = self.compile(); self.completed(job)
        generated = self.client.get('/api/workspace').json()['versions'][-1]
        self.assertEqual(generated['media_snapshot'][picture_id]['id'], media['id'])
        self.client.post(f'/api/cuts/{self.cut}/confirm', json=self.command(version_id=generated['id']))
        path = next((Path(self.temp.name) / 'media').iterdir()); path.unlink()
        blocked = self.client.post(f'/api/cuts/{self.cut}/compile', json=self.command(cut_id=self.cut, input=self.input, model='local-test'))
        self.assertEqual(blocked.status_code, 422)
        self.assertEqual(self.fake.calls, 1)
        response = self.client.post(f'/api/cuts/{self.cut}/confirm', json=self.command(version_id=generated['id']))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get(f"/api/cuts/{self.cut}/text?version_id={generated['id']}").text, generated['text'])

    def test_invalid_image_and_svg_are_rejected_without_model_calls(self):
        for content in [b'not an image', b'<svg xmlns="http://www.w3.org/2000/svg"></svg>']:
            response = self.client.post('/api/media', content=content, headers={'Content-Type': 'image/png'})
            self.assertEqual(response.status_code, 422)
        self.assertEqual(self.fake.calls, 0)

    def test_replacing_library_file_does_not_change_another_cut_binding(self):
        self.prepare()
        picture_id = self.input['pictures'][0]['id']
        original = self.client.post('/api/media', content=png()).json()
        response = self.client.put(f'/api/cuts/{self.cut}/pictures/{picture_id}/media', json=self.command(media_id=original['id']))
        self.assertEqual(response.status_code, 200, response.text)
        self.input = response.json()['draft_input']; self.input['pictures'][0].update(confirmed=True, linked_to_h3=True)
        self.client.put(f'/api/cuts/{self.cut}/draft', json=self.command(input=self.input))
        second = self.create_cut()
        self.client.post(f'/api/cuts/{second}/reuse', json=self.cut_command(second, kind='picture', reference_id=picture_id, slots={picture_id: 7}))
        replacement = self.client.post('/api/media', content=png('blue')).json()
        attached = self.client.put(f'/api/cuts/{second}/pictures/{picture_id}/media', json=self.cut_command(second, media_id=replacement['id']))
        self.assertEqual(attached.status_code, 200, attached.text)
        first = self.client.get(f'/api/cuts/{self.cut}').json()
        self.assertEqual(first['media_by_picture'][picture_id]['id'], original['id'])
        self.assertEqual(attached.json()['media_by_picture'][picture_id]['id'], replacement['id'])
        job, _ = self.compile(); self.completed(job)
        first = self.client.get(f'/api/cuts/{self.cut}').json()
        self.assertEqual(first['versions'][-1]['media_snapshot'][picture_id]['id'], original['id'])
        refreshed = self.client.post(f'/api/cuts/{self.cut}/reuse', json=self.command(kind='picture', reference_id=picture_id, slots={}))
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        self.assertEqual(refreshed.json()['media_by_picture'][picture_id]['id'], replacement['id'])
        self.assertFalse(refreshed.json()['draft_input']['pictures'][0]['linked_to_h3'])
        self.assertEqual(refreshed.json()['versions'][-1]['media_snapshot'][picture_id]['id'], original['id'])

    def test_cancelled_inference_cannot_apply_a_late_result(self):
        self.prepare(); self.fake.release.clear()
        job, _ = self.compile(); self.assertTrue(self.fake.entered.wait(timeout=2))
        command = self.command()
        cancelled = self.client.post(f"/api/jobs/{job['id']}/cancel", json=command)
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.fake.release.set(); self.app.state.worker.pending.join()
        latest = self.client.get(f"/api/jobs/{job['id']}").json()
        self.assertEqual(latest['status'], 'cancelled')
        self.assertEqual(self.client.get('/api/workspace').json()['versions'], [])
        self.assertEqual(self.client.post(f"/api/jobs/{job['id']}/cancel", json=command).json(), cancelled.json())
        self.assertEqual(self.fake.calls, 1)

    def test_sqlite_restart_marks_interrupted_jobs_and_rejects_late_completion(self):
        self.prepare(); self.fake.release.clear()
        job, _ = self.compile(); self.assertTrue(self.fake.entered.wait(timeout=2))
        reopened = Repository(self.temp.name)
        current = reopened.job(job['id'])
        self.assertEqual(current.status, 'failed')
        self.assertEqual(current.result.error_code, 'interrupted')
        self.fake.release.set(); self.app.state.worker.pending.join()
        self.assertEqual(self.client.get('/api/workspace').json()['versions'], [])
        self.assertEqual(reopened.workspace().state, 'error')

    def test_concurrent_repository_instances_guard_cut_and_reference_revisions(self):
        self.prepare(); first = self.client.get('/api/workspace').json(); second = self.create_cut()
        picture = self.input['pictures'][0]
        self.client.post(f'/api/cuts/{second}/reuse', json=self.cut_command(second, kind='picture', reference_id=picture['id'], slots={picture['id']: 6}))
        current = self.client.get(f'/api/cuts/{second}').json()
        raw = first['draft_input']; raw['pictures'][0]['description_en'] = 'new description'
        saved = self.client.put(f'/api/cuts/{self.cut}/draft', json=self.command(input=raw)).json()
        other = Repository(self.temp.name)
        with self.assertRaises(Exception) as conflict:
            other.save_draft(self.cut, DraftCommand(command_id=uuid4(), expected_revision=first['revision'], input=raw))
        self.assertEqual(conflict.exception.code, 'revision_conflict')
        raw2 = json.loads(json.dumps(current['draft_input'])); raw2['pictures'][0]['description_en'] = 'conflicting change'
        response = self.client.put(f'/api/cuts/{second}/draft', json=dict(command_id=str(uuid4()), expected_revision=current['revision'], input=raw2))
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['detail']['code'], 'revision_conflict')
        expected = current['draft_input']; expected['pictures'][0]['description_en'] = 'new description'
        self.assertEqual(self.client.get(f'/api/cuts/{second}').json()['draft_input'], expected)

    def test_trash_restore_preserves_versions_and_media(self):
        self.prepare(); job, _ = self.compile(); self.completed(job)
        before = self.client.get('/api/workspace').json()
        project = self.client.get('/api/projects').json()[0]
        command = {'command_id': str(uuid4()), 'expected_revision': project['revision'], 'trashed': True}
        trashed = self.client.put(f"/api/projects/{project['id']}/trash", json=command)
        self.assertEqual(trashed.status_code, 200)
        self.assertEqual(self.client.get(f'/api/cuts/{self.cut}').status_code, 404)
        restored = self.client.put(f"/api/projects/{project['id']}/trash", json={'command_id': str(uuid4()), 'expected_revision': trashed.json()['revision'], 'trashed': False})
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(self.client.get(f'/api/cuts/{self.cut}').json(), before)

    def test_receipts_reference_immutable_versions_without_duplicating_text(self):
        self.prepare(); job, _ = self.compile(); self.completed(job)
        command = self.command(input=self.input)
        first = self.client.put(f'/api/cuts/{self.cut}/draft', json=command).json()
        retry = self.client.put(f'/api/cuts/{self.cut}/draft', json=command).json()
        self.assertEqual(first, retry)
        with closing(sqlite3.connect(Path(self.temp.name) / 'workspace.sqlite3')) as db:
            receipt = json.loads(db.execute('SELECT result FROM commands WHERE id=?', (command['command_id'],)).fetchone()[0])
        self.assertNotIn('versions', receipt['view'])
        self.assertNotIn(first['versions'][0]['text'], json.dumps(receipt))
        self.assertEqual(receipt['view']['version_ids'], [first['versions'][0]['id']])

    def test_hash_menu_comes_from_backend_and_pictures_are_not_subjects(self):
        self.prepare()
        view = self.client.get('/api/workspace').json()
        self.assertEqual(len([t for t in view['tokens'] if t['kind'] == 'unit']), 3)
        self.assertEqual(len([t for t in view['tokens'] if t['kind'] == 'picture']), 4)
        self.assertIn({'kind': 'dialogue', 'id': 'd1', 'label': 'Battuta d1', 'token': 'battuta d1'}, view['tokens'])
        self.fake.plan = __import__('app.domain', fromlist=['Interpretation']).Interpretation(narrative_en='<Subject 1> adjusts the skirt from <Picture 2>. {{dialogue:d1}}', estimated_duration_s=8.0, question=None)
        job, _ = self.compile(); result = self.completed(job)
        self.assertEqual(result['status'], 'succeeded')
        self.assertIn('skirt from <Picture 2>', result['result']['prompt'])

    def test_unbound_ready_outfit_is_available_for_explicit_association(self):
        self.prepare()
        added = self.client.post(f'/api/cuts/{self.cut}/items', json=self.command(kind='picture')).json()
        picture = added['draft_input']['pictures'][-1]
        # Il token canonico esiste già prima delle conferme locali: il browser
        # potrà renderlo disponibile subito dopo i controlli dell'utente.
        token = next(t for t in added['tokens'] if t['id'] == picture['id'])
        self.assertEqual(token['association'], 'required')
        raw = added['draft_input']
        picture.update(role='outfit', name='Nuovo abito', description_en='a blue dress', confirmed=True, linked_to_h3=True)
        saved = self.client.put(f'/api/cuts/{self.cut}/draft', json=self.command(input=raw)).json()
        self.assertIn(picture['id'], [t['id'] for t in saved['tokens']])
        self.assertEqual(len(saved['draft_input']['active_units']), 3)
        self.assertFalse(any(s['picture_id'] == picture['id'] for u in saved['draft_input']['active_units'] for s in u['sources']))
        old_id = raw['active_units'][0]['sources'][1]['picture_id']
        raw['active_units'][0]['sources'][1] = {'picture_id': picture['id'], 'attribute': 'outfit'}
        raw['active_units'][0]['confirmed'] = False
        edited = self.client.put(f'/api/cuts/{self.cut}/draft', json=self.command(input=raw)).json()
        self.assertEqual(next(t for t in edited['tokens'] if t['id'] == picture['id'])['association'], 'bound')
        blocked = self.client.post(f'/api/cuts/{self.cut}/compile', json=self.command(cut_id=self.cut, input=raw, model='local-test'))
        self.assertEqual(blocked.status_code, 422)
        self.assertEqual(self.fake.calls, 0)
        raw['active_units'][0]['confirmed'] = True
        self.input = raw
        job, _ = self.compile(); result = self.completed(job)
        self.assertEqual(result['status'], 'succeeded')
        self.assertIn('wearing a blue dress from <Picture 5>', result['result']['prompt'])
        self.assertNotIn('wearing a skirt', result['result']['prompt'])
        self.assertIn(old_id, [p['id'] for p in raw['pictures']])
        self.assertEqual(self.fake.calls, 1)


class MigrationTests(unittest.TestCase):
    def test_m1_to_sqlite_keeps_original_backup_and_exact_history(self):
        with tempfile.TemporaryDirectory() as directory:
            original, command, previous = legacy_archive(directory)
            migrated = Repository(directory)
            current = migrated.workspace()
            self.assertEqual((Path(directory) / 'workspace.json').read_bytes(), previous)
            self.assertEqual((Path(directory) / 'workspace.before-sqlite.json').read_bytes(), previous)
            self.assertEqual(current.revision, original['revision'])
            self.assertEqual([v.text for v in current.versions], [v['text'] for v in original['versions']])
            self.assertTrue(all(v.input_snapshot is None for v in current.versions))
            self.assertEqual(migrated.save_draft(current.id, command).revision, original['revision'])
            with closing(migrated.connect()) as db:
                jobs = {r['id']: json.loads(r['data']) for r in db.execute('SELECT * FROM jobs')}
                versions = [json.loads(r['data']) for r in db.execute('SELECT * FROM versions ORDER BY rowid')]
            self.assertEqual(jobs, original['jobs'])
            self.assertEqual(versions, original['versions'])
            self.assertEqual(Repository(directory).workspace(), current)
            self.assertEqual(len(list(Path(directory).glob('workspace.before-sqlite*'))), 1)

    def test_failed_migration_is_atomic_and_original_survives(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'workspace.json'; content = b'{"bad": true}'
            path.write_bytes(content)
            with self.assertRaises(Exception): Repository(directory)
            self.assertEqual(path.read_bytes(), content)
            with closing(sqlite3.connect(Path(directory) / 'workspace.sqlite3')) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM projects').fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT count(*) FROM settings').fetchone()[0], 0)


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        repo = Repository(self.temp.name)
        self.access = Access(repo)
        self.password = 'correct-horse-h3-secret'
        self.access.set_password(self.password)
        self.fake = FakeOllama()
        self.app = create_app(self.temp.name, self.fake, lan=True, allowed_hosts=['mac.local'])
        self.client = TestClient(self.app, base_url='http://mac.local:8767', client=('192.168.1.40', 5000))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None); self.temp.cleanup()

    def login(self):
        response = self.client.post('/api/access/login', json={'password': self.password}, headers={'Origin': 'http://mac.local:8767'})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['csrf']

    def test_lan_requires_login_for_every_data_and_media_endpoint(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        for path in ['/api/projects', '/api/workspace', '/api/models', f'/api/media/{uuid4()}']:
            self.assertEqual(self.client.get(path).status_code, 401)
        csrf = self.login()
        self.assertEqual(self.client.get('/api/projects').status_code, 200)
        cookie = self.client.cookies.get('h3_session')
        self.assertIsNotNone(cookie)
        with closing(self.app.state.repository.connect()) as db:
            self.assertEqual(db.execute('SELECT token_hash FROM sessions').fetchone()[0], hashlib.sha256(cookie.encode()).hexdigest())
        self.assertNotIn(self.password, Path(self.temp.name, 'access.json').read_text())

    def test_csrf_origin_host_checks_and_local_only_password_configuration(self):
        csrf = self.login()
        body = {'command_id': str(uuid4()), 'expected_revision': 0, 'name': 'Da LAN'}
        self.assertEqual(self.client.post('/api/projects', json=body).status_code, 403)
        self.assertEqual(self.client.post('/api/projects', json=body, headers={'X-CSRF-Token': csrf, 'Origin': 'http://attacker.example'}).status_code, 403)
        self.assertEqual(self.client.post('/api/projects', json=body, headers={'X-CSRF-Token': csrf, 'Origin': 'http://mac.local:8767'}).status_code, 200)
        self.assertEqual(self.client.get('/api/projects', headers={'Host': 'attacker.example'}).status_code, 400)
        self.assertEqual(self.client.put('/api/access/password', json={'password': 'another-long-password'}, headers={'X-CSRF-Token': csrf}).status_code, 403)
        self.assertEqual(self.client.get('/api/access/bootstrap').status_code, 403)

    def test_draft_and_manual_text_are_shared_between_mac_and_lan_without_compiling(self):
        csrf = self.login()
        lan_headers = {'X-CSRF-Token': csrf, 'Origin': 'http://mac.local:8767'}
        mac = TestClient(self.app, base_url='http://127.0.0.1:8767', client=('127.0.0.1', 5001))
        self.addCleanup(mac.close)
        initial = mac.get('/api/workspace').json()
        path = f"/api/cuts/{initial['id']}"
        for writer, reader, headers, text in (
            (self.client, mac, lan_headers, 'Bozza modificata dal PC'),
            (mac, self.client, {}, 'Bozza modificata dal Mac'),
        ):
            current = writer.get(path).json()
            draft = {**current['draft_input'], 'request': text}
            saved = writer.put(f'{path}/draft', json={
                'command_id': str(uuid4()), 'expected_revision': current['revision'], 'input': draft,
            }, headers=headers)
            self.assertEqual(saved.status_code, 200, saved.text)
            received = reader.get(path).json()
            self.assertEqual(received['revision'], saved.json()['revision'])
            self.assertEqual(received['draft_input']['request'], text)
            self.assertIsNone(received['latest_job'])

        manual = self.client.put(f'{path}/manual', json={
            'command_id': str(uuid4()), 'expected_revision': received['revision'],
            'text': 'Prompt manuale condiviso.',
        }, headers=lan_headers)
        self.assertEqual(manual.status_code, 200, manual.text)
        received = mac.get(path).json()
        self.assertEqual(received['manual_version_id'], manual.json()['manual_version_id'])
        self.assertEqual(received['versions'][-1]['text'], 'Prompt manuale condiviso.')
        self.assertIsNone(received['latest_job'])
        self.assertEqual(self.fake.calls, 0)

    def test_password_rotation_invalidates_sessions_logout_and_login_throttle(self):
        csrf = self.login()
        self.client.post('/api/access/logout', headers={'X-CSRF-Token': csrf})
        self.assertEqual(self.client.get('/api/projects').status_code, 401)
        self.login(); self.app.state.access.set_password('different-long-password')
        self.assertEqual(self.client.get('/api/projects').status_code, 401)
        for _ in range(6):
            self.assertEqual(self.client.post('/api/access/login', json={'password': 'wrong'}).status_code, 401)
        self.assertEqual(self.client.post('/api/access/login', json={'password': 'wrong'}).status_code, 429)
        self.assertEqual(self.fake.calls, 0)


if __name__ == '__main__': unittest.main()
