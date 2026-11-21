import copy
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import create_app
from app.compiler import StructuralError, render
from app.contracts import WebCompileCommand
from app.domain import CompileInput, CurrentInterpretation
from app.interpreter import model_context
from app.repository import Repository
from app.store import digest
from test_api import FakeOllama
from test_picture_registry import catalogue_input


PLAN = CurrentInterpretation(narrative_en='<Subject 1> looks at the camera.',
    summary_en='<Subject 1> looks toward the camera.', estimated_duration_s=5.0, question=None)


class DefinitionTests(unittest.TestCase):
    def test_confirmed_picture_replaces_stale_subject_description_in_prompt_and_context(self):
        raw = catalogue_input(); raw['active_units'][0]['description_en'] = 'a red-haired woman'
        for mode in ['none', 'latent']:
            raw['continuity'] = dict(mode=mode, declared_state=None if mode=='none' else '<Subject 1> è in piedi.')
            data = CompileInput.model_validate(raw)
            prompt = render(data, PLAN, 'fresh').prompt
            self.assertIn('a young woman with long brown hair from <Picture 1>', prompt)
            self.assertNotIn('red-haired', prompt)
            self.assertNotIn('red-haired', json.dumps(model_context(data)))
            self.assertIn('wearing a black miniskirt from <Picture 2>', prompt)
        # A later manual correction of the Picture follows the same path as vision/translation.
        raw['pictures'][0]['description_en'] = 'a woman with short black hair'
        self.assertIn('short black hair', render(CompileInput.model_validate(raw), PLAN, 'corrected').prompt)
        self.assertEqual(raw['active_units'][0]['description_en'], 'a red-haired woman')

    def test_explicit_manual_definition_and_shared_photo_mapping_are_authoritative(self):
        raw = catalogue_input(); unit = raw['active_units'][0]
        unit.update(definition_mode='manual', description_en='the woman on the left')
        second = copy.deepcopy(unit); second.update(subject=2, name='Beth', description_en='the woman on the right')
        raw['active_units'].append(second)
        data = CompileInput.model_validate(raw); prompt = render(data, PLAN, 'mapping').prompt
        self.assertIn('the woman on the left from <Picture 1>', prompt)
        self.assertIn('the woman on the right from <Picture 1>', prompt)
        self.assertEqual(model_context(data)['active_references'][0]['description_en'], 'the woman on the left')

    def test_context_identity_never_takes_description_from_outfit_picture(self):
        raw = catalogue_input(); raw['active_units'][0]['description_en'] = 'a woman with brown hair'
        raw['active_units'][0]['sources'][0] = dict(origin='context', attribute='identity')
        raw['continuity'] = dict(mode='latent', declared_state='<Subject 1> è in piedi.')
        prompt = render(CompileInput.model_validate(raw), PLAN, 'context').prompt
        self.assertIn('<Subject 1> is a woman with brown hair, wearing a black miniskirt', prompt)
        self.assertNotIn('woman with brown hair from <Picture 2>', prompt)
        self.assertNotIn('<Picture 1>', prompt)

    def test_picture_definition_needs_no_duplicate_subject_text_but_manual_cannot_be_empty(self):
        raw = catalogue_input(); raw['active_units'][0]['description_en'] = ''
        data = CompileInput.model_validate(raw)
        self.assertIn('long brown hair', render(data, PLAN, 'no-copy').prompt)
        raw['active_units'][0]['definition_mode'] = 'manual'
        with self.assertRaises(ValidationError): CompileInput.model_validate(raw)

    def test_ambient_default_toggle_and_dialogue_do_not_change_dialogue_words(self):
        raw = catalogue_input(); raw['dialogues'] = [dict(id='d1',text='  Ciao!  ',language='Italian',speaker_subject=1,confirmed=True)]
        plan = PLAN.model_copy(update={'narrative_en':'{{dialogue:d1}}'})
        enabled = render(CompileInput.model_validate(raw), plan, 'on').prompt
        self.assertIn('overall_soundscape:\nAmbient sounds.\n', enabled)
        self.assertNotIn('On-screen speech', enabled)
        raw['ambient_sound'] = False
        disabled = render(CompileInput.model_validate(raw), plan, 'off').prompt
        self.assertIn('overall_soundscape:\nN/A\n', disabled)
        for prompt in [enabled, disabled]: self.assertIn('<d>[Italian]   Ciao!  </d>.', prompt)

    def test_ambient_layer_prevents_exclusive_fully_copy_audio_claim(self):
        raw = dict(request='Una stanza vuota.',declared_duration_s=5.0,audio_references=[dict(
            id='a1',slot=1,media_id='fixture',role='sound',mode='copy',sample_rate=8000,sample_count=40000,
            channels=1,measured_duration_s=5.0,description_en='the recorded room tone',
            confirmed=True,linked_to_h3=True,exclusive_full_track=True)])
        plan = PLAN.model_copy(update={'narrative_en':'An empty room.','summary_en':'An empty room remains in view.'})
        self.assertIn('partially_copy', render(CompileInput.model_validate(raw),plan,'layer').prompt)
        raw['ambient_sound'] = False
        self.assertIn('fully_copy', render(CompileInput.model_validate(raw),plan,'exclusive').prompt)
        raw['soundscape_text'] = 'Rumore soffuso del traffico.'
        plan = plan.model_copy(update={'soundscape_en': 'Soft traffic noise.'})
        prompt = render(CompileInput.model_validate(raw), plan, 'custom-layer').prompt
        self.assertIn('partially_copy', prompt)
        self.assertIn('overall_soundscape:\nSoft traffic noise. Copy <Audio 1> for supplied sound.', prompt)

    def test_custom_soundscape_is_translated_separately_and_respects_toggle(self):
        raw = catalogue_input()
        original = CompileInput.model_validate(raw).model_dump()
        self.assertEqual(CompileInput.model_validate(raw | {'soundscape_text': ''}).model_dump(), original)
        raw.update(ambient_sound=False, soundscape_text='Suoni ambientali, rumore soffuso del traffico e fruscio delle lenzuola.')
        data = CompileInput.model_validate(raw)
        translated = 'Ambient sounds, soft traffic noise and rustling bed sheets.'
        plan = PLAN.model_copy(update={'soundscape_en': translated})
        prompt = render(data, plan, 'custom-soundscape').prompt
        self.assertIn('overall_soundscape:\n' + translated + '\n\nnon_diegetic_music:', prompt)
        self.assertEqual(prompt.count(translated), 1)
        self.assertEqual(model_context(data)['soundscape_text'], raw['soundscape_text'])
        enabled = CompileInput.model_validate(raw | {'ambient_sound': True})
        self.assertNotIn('soundscape_text', model_context(enabled))
        self.assertIn('overall_soundscape:\nAmbient sounds.\n', render(enabled, PLAN, 'automatic').prompt)
        self.assertEqual(enabled.soundscape_text, raw['soundscape_text'])

    def test_missing_or_structurally_invalid_soundscape_translation_is_rejected(self):
        data = CompileInput.model_validate(catalogue_input() | {'ambient_sound': False, 'soundscape_text': 'Traffico in lontananza.'})
        for text in [None, '', '<d>Words</d>', 'summary: extra section', '{{dialogue:d1}}', '<Audio 99> plays.', '<Subject 1 rustles sheets.']:
            with self.subTest(text=text), self.assertRaises(StructuralError):
                render(data, PLAN.model_copy(update={'soundscape_en': text}), 'bad-soundscape')

    def test_old_compile_receipt_remains_retryable_but_preference_changes_are_not_the_same_command(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Repository(folder); cut = repo.workspace().id
            raw = catalogue_input()
            command = WebCompileCommand.model_validate_json(json.dumps(dict(command_id=str(uuid4()),cut_id=str(cut),expected_revision=0,input=raw,model='local-test')))
            old = command.model_dump(mode='json'); old['input'].pop('ambient_sound')
            for unit in old['input']['active_units']: unit.pop('definition_mode')
            fingerprint = digest(dict(operation='compile',cut_id=str(cut),command=old))
            self.assertIn(fingerprint, repo._receipt_hashes('compile',cut,command))
            changed = command.model_copy(update={'input': command.input.model_copy(update={'ambient_sound': False})})
            self.assertNotIn(fingerprint, repo._receipt_hashes('compile',cut,changed))


class DefinitionApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.fake = FakeOllama(); self.fake.plan = PLAN
        self.app = create_app(self.temp.name,self.fake)
        self.client = TestClient(self.app,base_url='http://127.0.0.1:8767'); self.client.__enter__()
        self.cut = self.client.get('/api/workspace').json()['id']
        for kind in ['picture','unit']:
            view = self.client.post(f'/api/cuts/{self.cut}/items',json=self.command(kind=kind)).json()
        self.raw = view['draft_input']; picture = self.raw['pictures'][0]
        picture.update(name='Identità',description_en='a woman with brown hair',confirmed=True,linked_to_h3=True)
        self.raw['active_units'][0].update(name='Ann',description_en='a red-haired woman',confirmed=True,
            sources=[dict(picture_id=picture['id'],attribute='identity')])
        self.raw.update(request='<Subject 1> guarda la camera.',declared_duration_s=5.0)
        self.save(self.raw)
    def tearDown(self):
        self.client.__exit__(None,None,None);self.temp.cleanup()
    def view(self): return self.client.get(f'/api/cuts/{self.cut}').json()
    def command(self,**extra): return dict(command_id=str(uuid4()),expected_revision=self.view()['revision'],**extra)
    def save(self,raw):
        result=self.client.put(f'/api/cuts/{self.cut}/draft',json=self.command(input=raw))
        self.assertEqual(result.status_code,200,result.text);return result.json()
    def compile(self):
        response=self.client.post(f'/api/cuts/{self.cut}/compile',json=self.command(cut_id=self.cut,input=self.view()['draft_input'],model='local-test'))
        self.assertEqual(response.status_code,202,response.text);self.app.state.worker.pending.join()
        return self.view()['versions'][-1]

    def test_next_context_subject_uses_selected_version_description_and_keeps_old_text(self):
        first = self.compile(); oldtext = first['text']; self.assertIn('brown hair',oldtext)
        self.raw['pictures'][0]['description_en'] = 'a woman with black hair'; self.save(self.raw)
        scene = self.client.get('/api/projects').json()[0]['scenes'][0]
        second=self.client.post(f"/api/scenes/{scene['id']}/cuts",json=dict(command_id=str(uuid4()),expected_revision=scene['revision'],name='Segue')).json()
        self.cut=second['id']; raw=second['draft_input'];raw['continuity']=dict(mode='latent',declared_state='<Subject 1> è in piedi.',previous_cut_id=first['cut_id'] if 'cut_id' in first else scene['cuts'][0]['id'],previous_version_id=first['id'])
        self.save(raw)
        view=self.client.post(f'/api/cuts/{self.cut}/context-subject',json=self.command(subject=1)).json()
        unit=view['draft_input']['active_units'][0]
        self.assertEqual(unit['description_en'],'a woman with brown hair')
        self.assertEqual(unit['definition_mode'],'manual');self.assertFalse(unit['confirmed'])
        with closing(sqlite3.connect(self.app.state.repository.path)) as db:
            stored=json.loads(db.execute('SELECT data FROM versions WHERE id=?',(first['id'],)).fetchone()[0])
        self.assertEqual(stored['text'],oldtext)
        self.assertEqual(stored['input_snapshot']['pictures'][0]['description_en'],'a woman with brown hair')

    def test_applied_vision_description_reaches_next_compile_without_rewriting_previous_version(self):
        from test_m2 import png
        first = self.compile()
        self.fake.keep_alive = '0'
        self.fake.models = lambda: [dict(name='local-test',digest='fixture',capabilities=['completion','vision'])]
        def respond(path,payload):
            if path == '/api/show': return dict(capabilities=['completion','vision'])
            properties=payload['format']['properties']
            content=dict(red_square=True,blue_circle=True) if 'red_square' in properties else dict(description='a woman with short dark brown hair')
            return dict(done=True,done_reason='stop',message=dict(content=json.dumps(content)))
        self.fake._request=respond
        picture_id=self.raw['pictures'][0]['id']
        media=self.client.post('/api/media',content=png()).json()
        attached=self.client.put(f'/api/cuts/{self.cut}/pictures/{picture_id}/media',json=self.command(media_id=media['id']))
        self.assertEqual(attached.status_code,200,attached.text)
        def job(kind,target=None):
            response=self.client.post(f'/api/cuts/{self.cut}/assistance',json=self.command(kind=kind,target_id=target,model='local-test'))
            self.assertEqual(response.status_code,202,response.text);self.app.state.worker.pending.join()
            return self.client.get('/api/assistance/jobs/'+response.json()['id']).json()
        self.assertEqual(job('vision_trial')['status'],'succeeded')
        analysis=job('image_analyze',picture_id)
        applied=self.client.post(f"/api/cuts/{self.cut}/assistance/{analysis['id']}/apply",json=self.command())
        self.assertEqual(applied.status_code,200,applied.text)
        raw=applied.json()['draft_input'];raw['pictures'][0].update(confirmed=True,linked_to_h3=True);self.save(raw)
        current=self.compile()
        self.assertIn('short dark brown hair',current['text']);self.assertNotIn('red-haired',current['text'])
        self.assertEqual(self.client.get(f"/api/cuts/{self.cut}/text?version_id={first['id']}").text,first['text'])
        self.assertEqual(self.fake.calls,2)

    def test_shared_picture_updates_are_visible_but_do_not_rewrite_other_cut_or_versions(self):
        first=self.view(); picture=first['draft_input']['pictures'][0]
        scene=self.client.get('/api/projects').json()[0]['scenes'][0]
        second=self.client.post(f"/api/scenes/{scene['id']}/cuts",json=dict(command_id=str(uuid4()),expected_revision=scene['revision'],name='Secondo')).json()
        response=self.client.post(f"/api/cuts/{second['id']}/reuse",json=dict(command_id=str(uuid4()),expected_revision=second['revision'],kind='picture',reference_id=picture['id'],slots={picture['id']:1}))
        self.assertEqual(response.status_code,200,response.text)
        second_before=response.json()
        raw=self.view()['draft_input'];raw['pictures'][0]['description_en']='a replacement character';self.save(raw)
        with TestClient(self.app,base_url='http://127.0.0.1:8767') as other_browser:
            same_cut=other_browser.get(f'/api/cuts/{self.cut}').json()
            unchanged=other_browser.get(f"/api/cuts/{second['id']}").json()
        self.assertEqual(same_cut['draft_input']['pictures'][0]['description_en'],'a replacement character')
        self.assertNotIn(picture['id'],same_cut['reference_updates'])
        self.assertIn(picture['id'],unchanged['reference_updates'])
        self.assertEqual(unchanged['draft_input'],second_before['draft_input'])
        self.assertEqual(unchanged['revision'],second_before['revision'])
        self.assertEqual(self.fake.calls,0)

    def test_ambient_choice_persists_and_new_cut_defaults_on(self):
        raw=self.view()['draft_input'];raw['ambient_sound']=False;self.save(raw)
        first=self.compile();self.assertNotIn('Ambient sounds.',first['text'])
        self.assertFalse(first['input_snapshot']['ambient_sound'])
        self.assertFalse(self.view()['draft_input']['ambient_sound'])
        scene=self.client.get('/api/projects').json()[0]['scenes'][0]
        second=self.client.post(f"/api/scenes/{scene['id']}/cuts",json=dict(command_id=str(uuid4()),expected_revision=scene['revision'],name='Nuovo')).json()
        self.assertTrue(CompileInput.model_construct(**second['draft_input']).ambient_sound)
        self.assertEqual(self.fake.calls,1)

    def test_custom_soundscape_is_saved_in_snapshot_without_rewriting_previous_version(self):
        first = self.compile()
        raw = self.view()['draft_input']
        raw.update(ambient_sound=False, soundscape_text='Traffico soffuso e fruscio delle lenzuola.')
        self.save(raw)
        self.fake.plan = PLAN.model_copy(update={'soundscape_en': 'Soft traffic noise and rustling bed sheets.'})
        second = self.compile()
        self.assertIn('overall_soundscape:\nSoft traffic noise and rustling bed sheets.', second['text'])
        self.assertEqual(second['input_snapshot']['soundscape_text'], raw['soundscape_text'])
        self.assertEqual(self.view()['draft_input']['soundscape_text'], raw['soundscape_text'])
        self.assertEqual(self.client.get(f"/api/cuts/{self.cut}/text?version_id={first['id']}").text, first['text'])
