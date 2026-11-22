import io
import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import numpy as np
import soundfile as sf
from fastapi.testclient import TestClient

from app.api import create_app
from app.analysis import encoded_image, infer
from app.compiler import render
from app.contracts import AddItemCommand, DraftCommand
from app.domain import AudioReference, CompileInput, Interpretation
from app.interpreter import input_hash, model_context
from app.repository import Repository
from test_api import FakeOllama
from test_m2 import png
from test_picture_registry import catalogue_input


class VisionClient(FakeOllama):
    keep_alive = '0'
    def __init__(self):
        super().__init__(); self.chat_calls = 0; self.digest = 'vision-v1'; self.mode_vision = 'ok'
        self.vision_entered, self.vision_release = threading.Event(), threading.Event(); self.vision_release.set()
        self.plan = Interpretation(narrative_en='An empty room.', estimated_duration_s=5.0, question=None)
    def models(self):
        return [{'name':'text-test','digest':'text-v1'},{'name':'vision-test','digest':self.digest}]
    def _request(self, path, payload):
        if path == '/api/show': return {'capabilities':['completion','vision'] if payload['model']=='vision-test' else ['completion']}
        assert path == '/api/chat'; self.chat_calls += 1; self.last_payload = payload
        self.vision_entered.set(); self.vision_release.wait(timeout=3)
        if self.mode_vision == 'broken': return {'done':True,'message':{'content':'bad json'}}
        properties = payload['format']['properties']
        content = {'red_square':True,'blue_circle':True} if 'red_square' in properties else {'description':'a blue short-sleeved shirt'}
        return {'done':True,'done_reason':'stop','message':{'content':json.dumps(content)},'prompt_eval_count':100,'eval_count':10}


def wav(seconds=5, format='WAV'):
    buffer = io.BytesIO(); sf.write(buffer, np.zeros(round(seconds*8000),dtype='float32'),8000,format=format)
    return buffer.getvalue()


def aac():
    import av
    buffer = io.BytesIO()
    with av.open(buffer, mode='w', format='adts') as container:
        stream = container.add_stream('aac', rate=22050)
        stream.layout = 'mono'
        samples = np.sin(np.arange(22050) * (2 * np.pi * 220 / 22050)).astype('float32').reshape(1, -1) * 0.1
        frame = av.AudioFrame.from_ndarray(samples, format='fltp', layout='mono')
        frame.sample_rate = 22050
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return buffer.getvalue()


class M3ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.fake = VisionClient()
        self.app = create_app(self.temp.name,self.fake); self.client = TestClient(self.app,base_url='http://127.0.0.1:8767'); self.client.__enter__()
        self.cut = self.view()['id']
    def tearDown(self):
        self.fake.release.set(); self.fake.vision_release.set(); self.client.__exit__(None,None,None); self.temp.cleanup()
    def view(self): return self.client.get('/api/workspace').json()
    def command(self, **extra): return {'command_id':str(uuid4()),'expected_revision':self.view()['revision'],**extra}
    def save(self, raw):
        response=self.client.put(f'/api/cuts/{self.cut}/draft',json=self.command(input=raw)); self.assertEqual(response.status_code,200,response.text); return response.json()
    def completed(self, job):
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            job=self.client.get(f"/api/assistance/jobs/{job['id']}").json()
            if job['status'] not in {'queued','running'}: return job
            time.sleep(.01)
        self.fail('Assistenza non terminata')
    def run_job(self, kind, target=None, force=False):
        response=self.client.post(f'/api/cuts/{self.cut}/assistance',json=self.command(kind=kind,target_id=target,model='text-test' if kind=='description_translate' else 'vision-test',force=force))
        self.assertEqual(response.status_code,202,response.text); return self.completed(response.json())
    def trial(self):
        result=self.run_job('vision_trial'); self.assertEqual(result['status'],'succeeded',result)
    def picture(self):
        current=self.client.post(f'/api/cuts/{self.cut}/items',json=self.command(kind='picture')).json()
        raw=current['draft_input']; raw['pictures'][0].update(role='outfit',name='Abito',description_en='manual description')
        self.save(raw); id=raw['pictures'][0]['id']
        media=self.client.post('/api/media',content=png()).json()
        response=self.client.put(f'/api/cuts/{self.cut}/pictures/{id}/media',json=self.command(media_id=media['id']))
        self.assertEqual(response.status_code,200,response.text)
        return id,media
    def apply(self, job): return self.client.post(f"/api/cuts/{self.cut}/assistance/{job['id']}/apply",json=self.command())
    def audio(self, seconds=5, format='WAV'):
        current=self.client.post(f'/api/cuts/{self.cut}/items',json=self.command(kind='audio')).json()
        id=current['draft_input']['audio_references'][-1]['id']
        media=self.client.post('/api/audio-media',content=wav(seconds,format),headers={'X-File-Name':'file.not-audio','Content-Type':'image/png'})
        self.assertEqual(media.status_code,200,media.text)
        response=self.client.put(f'/api/cuts/{self.cut}/audio/{id}/media',json=self.command(media_id=media.json()['id']))
        self.assertEqual(response.status_code,200,response.text)
        return id,media.json()

    def test_capability_selection_requires_real_trial_and_settings_are_independent(self):
        id,_=self.picture()
        response=self.client.post(f'/api/cuts/{self.cut}/assistance',json=self.command(kind='image_analyze',target_id=id,model='text-test'))
        self.assertEqual(response.status_code,422); self.assertEqual(self.fake.chat_calls,0)
        response=self.client.post(f'/api/cuts/{self.cut}/assistance',json=self.command(kind='image_analyze',target_id=id,model='vision-test'))
        self.assertEqual(response.status_code,422); self.assertEqual(response.json()['detail']['code'],'vision_not_tested')
        body={'command_id':str(uuid4()),'expected_revision':0,'text_model':'text-test','vision_model':'vision-test'}
        saved=self.client.put('/api/assistance/settings',json=body)
        self.assertEqual(saved.status_code,200,saved.text)
        self.assertEqual(self.client.put('/api/assistance/settings',json=body).json(),saved.json())
        self.assertEqual(self.client.get('/api/assistance/settings').json()['text_model'],'text-test')
        self.trial()
        models=self.client.get('/api/assistance/models').json()
        self.assertTrue(next(m for m in models if m['name']=='vision-test')['vision_tested'])

    def test_one_image_proposal_explicit_apply_confirmation_and_cache_without_calls(self):
        id,_=self.picture(); self.trial(); proposal=self.run_job('image_analyze',id)
        self.assertEqual(proposal['result']['metrics']['inference_calls'],1)
        self.assertEqual(self.fake.chat_calls,2)
        self.assertEqual(self.view()['draft_input']['pictures'][0]['description_en'],'manual description')
        applied=self.apply(proposal); self.assertEqual(applied.status_code,200,applied.text)
        self.assertEqual(applied.json()['draft_input']['pictures'][0]['description_en'],'a blue short-sleeved shirt')
        self.assertFalse(applied.json()['draft_input']['pictures'][0]['confirmed'])
        self.assertEqual(applied.json()['draft_input']['active_units'],[])
        cached=self.run_job('image_analyze',id)
        self.assertTrue(cached['result']['metrics']['cache_hit']); self.assertEqual(cached['result']['metrics']['inference_calls'],0)
        self.assertEqual(self.fake.chat_calls,2)
        # La proposta cache non riscrive neppure la descrizione già applicata.
        self.assertEqual(self.view()['revision'],applied.json()['revision'])

    def test_character_sheet_uses_full_picture_and_a_separate_cache(self):
        picture_id, _ = self.picture()
        self.trial()
        unsupported = self.client.post(
            f'/api/cuts/{self.cut}/assistance',
            json=self.command(kind='image_character_sheet', target_id=picture_id, model='vision-test'),
        )
        self.assertEqual(unsupported.status_code, 422)
        raw = self.view()['draft_input']
        raw['pictures'][0]['role'] = 'identity'
        self.save(raw)
        self.run_job('image_analyze', picture_id)

        first = self.run_job('image_character_sheet', picture_id)
        self.assertEqual(first['status'], 'succeeded', first)
        self.assertEqual(first['result']['metrics']['inference_calls'], 1)
        self.assertEqual(self.fake.last_payload['messages'][-1]['images'], [encoded_image(png())])

        proxy = self.client.post('/api/media', content=png('blue')).json()
        attached = self.client.put(
            f'/api/cuts/{self.cut}/pictures/{picture_id}/proxy',
            json=self.command(media_id=proxy['id']),
        )
        self.assertEqual(attached.status_code, 200, attached.text)
        cached = self.run_job('image_character_sheet', picture_id)
        self.assertTrue(cached['result']['metrics']['cache_hit'])
        fresh = self.run_job('image_character_sheet', picture_id, force=True)
        self.assertEqual(self.fake.last_payload['messages'][-1]['images'], [encoded_image(png())])
        self.assertEqual(self.view()['draft_input']['pictures'][0]['description_en'], 'manual description')
        applied = self.apply(fresh)
        self.assertEqual(applied.status_code, 200, applied.text)
        self.assertFalse(applied.json()['draft_input']['pictures'][0]['confirmed'])
        self.assertEqual(applied.json()['draft_input']['active_units'], [])

    def test_correction_during_vision_is_authoritative_and_late_apply_rejected(self):
        id,_=self.picture(); self.trial(); self.fake.vision_entered.clear(); self.fake.vision_release.clear()
        response=self.client.post(f'/api/cuts/{self.cut}/assistance',json=self.command(kind='image_analyze',target_id=id,model='vision-test'))
        self.assertTrue(self.fake.vision_entered.wait(timeout=2))
        raw=self.view()['draft_input']; raw['pictures'][0].update(description_en='CORRECTED BY USER',confirmed=True)
        self.save(raw); self.fake.vision_release.set(); late=self.completed(response.json())
        self.assertTrue(late['stale']); self.assertEqual(self.apply(late).status_code,409)
        self.assertEqual(self.view()['draft_input']['pictures'][0]['description_en'],'CORRECTED BY USER')
        self.assertTrue(self.view()['draft_input']['pictures'][0]['confirmed'])

    def test_role_and_digest_are_separate_cache_keys_and_invalid_response_has_no_retry(self):
        id,_=self.picture(); self.trial(); self.run_job('image_analyze',id)
        raw=self.view()['draft_input']; raw['pictures'][0]['role']='shoes'; self.save(raw)
        self.run_job('image_analyze',id); self.assertEqual(self.fake.chat_calls,3)
        self.fake.digest='vision-v2'
        response=self.client.post(f'/api/cuts/{self.cut}/assistance',json=self.command(kind='image_analyze',target_id=id,model='vision-test'))
        self.assertEqual(response.status_code,422)
        self.trial(); self.fake.mode_vision='broken'
        job=self.run_job('image_analyze',id,force=True)
        self.assertEqual(job['status'],'failed'); self.assertEqual(self.fake.chat_calls,5)
        self.assertEqual(self.view()['draft_input']['pictures'][0]['description_en'],'manual description')

    def test_proxy_is_distinct_from_final_media_and_replacement_invalidates_proposal(self):
        id,final=self.picture(); self.trial()
        proxy=self.client.post('/api/media',content=png('blue')).json()
        attached=self.client.put(f'/api/cuts/{self.cut}/pictures/{id}/proxy',json=self.command(media_id=proxy['id']))
        self.assertEqual(attached.status_code,200,attached.text)
        view=attached.json(); self.assertEqual(view['media_by_picture'][id]['id'],final['id']); self.assertEqual(view['proxy_by_picture'][id]['id'],proxy['id'])
        job=self.run_job('image_analyze',id)
        replacement=self.client.post('/api/media',content=png('red')).json()
        self.client.put(f'/api/cuts/{self.cut}/pictures/{id}/media',json=self.command(media_id=replacement['id']))
        self.assertEqual(self.apply(job).status_code,409)
        self.assertEqual(self.view()['proxy_by_picture'][id]['id'],proxy['id'])

    def test_translation_preserves_original_and_is_never_implicit(self):
        id,_=self.picture(); raw=self.view()['draft_input']
        raw['pictures'][0].update(description_en='gonna blu corretta',description_language='Italian')
        self.save(raw); self.assertEqual(self.fake.chat_calls,0)
        job=self.run_job('description_translate',id); applied=self.apply(job)
        self.assertEqual(applied.status_code,200,applied.text)
        picture=applied.json()['draft_input']['pictures'][0]
        self.assertEqual(picture['original_description'],'gonna blu corretta'); self.assertEqual(picture['original_language'],'Italian')
        self.assertEqual(picture['description_language'],'English'); self.assertFalse(picture['confirmed'])
        self.assertEqual(self.fake.chat_calls,1)

    def test_text_and_vision_are_serialized_by_the_same_worker(self):
        id,_=self.picture(); self.trial(); self.fake.release.clear()
        raw=self.view()['draft_input']; raw['request']='Una stanza vuota.'; self.save(raw)
        response=self.client.post(f'/api/cuts/{self.cut}/compile',json=self.command(cut_id=self.cut,input=raw,model='text-test'))
        self.assertEqual(response.status_code,202,response.text); self.assertTrue(self.fake.entered.wait(timeout=2))
        response=self.client.post(f'/api/cuts/{self.cut}/assistance',json=self.command(kind='image_analyze',target_id=id,model='vision-test'))
        self.assertEqual(response.status_code,202,response.text); self.assertEqual(self.fake.chat_calls,1)
        self.assertEqual(self.client.get(f"/api/assistance/jobs/{response.json()['id']}").json()['status'],'queued')
        self.fake.release.set(); completed=self.completed(response.json()); self.assertEqual(completed['status'],'succeeded')
        self.assertEqual(self.fake.chat_calls,2); self.assertEqual(self.fake.calls,1)

    def test_cancel_and_restart_discard_late_auxiliary_results(self):
        id,_=self.picture(); self.trial(); self.fake.vision_entered.clear(); self.fake.vision_release.clear()
        response=self.client.post(f'/api/cuts/{self.cut}/assistance',json=self.command(kind='image_analyze',target_id=id,model='vision-test'))
        self.assertTrue(self.fake.vision_entered.wait(timeout=2))
        command=self.command()
        cancelled=self.client.post(f"/api/cuts/{self.cut}/assistance/{response.json()['id']}/cancel",json=command)
        self.assertEqual(cancelled.status_code,200,cancelled.text)
        self.fake.vision_release.set(); self.app.state.worker.pending.join()
        self.assertEqual(self.client.get(f"/api/assistance/jobs/{response.json()['id']}").json()['status'],'cancelled')
        self.assertEqual(self.client.post(f"/api/cuts/{self.cut}/assistance/{response.json()['id']}/cancel",json=command).json(),cancelled.json())
        self.fake.vision_entered.clear(); self.fake.vision_release.clear()
        response=self.client.post(f'/api/cuts/{self.cut}/assistance',json=self.command(kind='image_analyze',target_id=id,model='vision-test'))
        self.assertTrue(self.fake.vision_entered.wait(timeout=2))
        restarted=create_app(self.temp.name,self.fake)
        with TestClient(restarted,base_url='http://127.0.0.1:8767') as client:
            job=client.get(f"/api/assistance/jobs/{response.json()['id']}").json()
            self.assertEqual(job['status'],'failed')
        self.fake.vision_release.set(); self.app.state.worker.pending.join()
        self.assertEqual(self.view()['draft_input']['pictures'][0]['description_en'],'manual description')

    def test_unrelated_request_edit_does_not_invalidate_image_proposal(self):
        id,_=self.picture(); self.trial(); job=self.run_job('image_analyze',id)
        raw=self.view()['draft_input']; raw['request']='Richiesta modificata senza cambiare la Picture.'; self.save(raw)
        self.assertFalse(self.client.get(f"/api/assistance/jobs/{job['id']}").json()['stale'])
        self.assertEqual(self.apply(job).status_code,200)

    def test_additive_language_defaults_do_not_make_m2_reference_stale(self):
        id,_=self.picture(); self.trial(); job=self.run_job('image_analyze',id)
        raw=self.view()['draft_input']
        raw['pictures'][0].update(description_language='English',use_original_language=False,original_description=None,original_language=None)
        raw['audio_references']=[]
        self.save(raw)
        self.assertFalse(self.client.get(f"/api/assistance/jobs/{job['id']}").json()['stale'])
        self.assertEqual(self.apply(job).status_code,200)

    def test_wav_mp3_real_decoding_metadata_authority_and_optional_asr(self):
        id,media=self.audio(5,'MP3')
        self.assertEqual(media['content_type'],'audio/mpeg'); self.assertEqual(media['sample_count'],40000); self.assertEqual(media['duration_s'],5)
        self.assertEqual(self.client.get(f"/api/audio-media/{media['id']}").status_code,200)
        raw=self.view()['draft_input']; raw['audio_references'][0]['sample_count']=1
        self.assertEqual(self.client.put(f'/api/cuts/{self.cut}/draft',json=self.command(input=raw)).status_code,422)
        with patch('app.transcription.status',return_value={'available':False,'message':'ASR assente'}):
            response=self.client.post(f'/api/cuts/{self.cut}/assistance',json=self.command(kind='audio_asr',target_id=id,model='local-whisper'))
            self.assertEqual(response.status_code,409)
        self.assertEqual(self.fake.calls,0); self.assertEqual(self.fake.chat_calls,0)

    def test_aac_named_mp3_keeps_source_and_supplies_valid_wav_for_playback_and_asr(self):
        source = aac()
        response = self.client.post('/api/audio-media', content=source,
            headers={'X-File-Name': 'mamma.mp3', 'Content-Type': 'audio/mpeg'})
        self.assertEqual(response.status_code, 200, response.text)
        media = response.json()
        self.assertEqual(media['content_type'], 'audio/aac')
        self.assertEqual(media['sample_rate'], 22050)
        self.assertEqual(media['channels'], 1)
        original = self.client.get(f"/api/audio-media/{media['id']}?preview=false")
        self.assertEqual(original.content, source)
        self.assertEqual(original.headers['content-type'], 'audio/aac')
        preview = self.client.get(f"/api/audio-media/{media['id']}")
        with sf.SoundFile(io.BytesIO(preview.content)) as audio:
            self.assertEqual(audio.format, 'WAV')
            self.assertEqual(audio.frames, media['sample_count'])
            self.assertEqual(audio.samplerate, 22050)
        again = self.client.post('/api/audio-media', content=source).json()
        self.assertEqual(again['id'], media['id'])

    def test_three_audio_slots_do_not_renumber_or_leak_to_next_cut(self):
        for _ in range(3): self.client.post(f'/api/cuts/{self.cut}/items',json=self.command(kind='audio'))
        self.assertEqual(self.client.post(f'/api/cuts/{self.cut}/items',json=self.command(kind='audio')).status_code,422)
        raw=self.view()['draft_input']; raw['audio_references'].pop(1); self.save(raw)
        added=self.client.post(f'/api/cuts/{self.cut}/items',json=self.command(kind='audio')).json()
        self.assertEqual([a['slot'] for a in added['draft_input']['audio_references']],[1,3,2])
        scene=self.client.get('/api/projects').json()[0]['scenes'][0]
        created=self.client.post(f"/api/scenes/{scene['id']}/cuts",json={'command_id':str(uuid4()),'expected_revision':scene['revision'],'name':'Nuovo'}).json()
        self.assertEqual(created['draft_input'].get('audio_references',[]),[])

    def test_audio_copy_prompt_and_confirmation_use_measured_file_snapshot(self):
        id,media=self.audio(5)
        raw=self.view()['draft_input']; raw['request']='Una stanza vuota con il suono indicato.'; raw['declared_duration_s']=5.0; raw['ambient_sound']=False
        audio=raw['audio_references'][0]; audio.update(role='sound',mode='copy',description_en='a supplied sound',confirmed=True,linked_to_h3=True,exclusive_full_track=True)
        self.save(raw)
        response=self.client.post(f'/api/cuts/{self.cut}/compile',json=self.command(cut_id=self.cut,input=raw,model='text-test'))
        self.assertEqual(response.status_code,202,response.text); self.app.state.worker.pending.join()
        view=self.view(); version=view['versions'][-1]
        self.assertIn('<Audio 1>',version['text']); self.assertIn('fully_copy',version['text'])
        self.assertEqual(version['media_snapshot']['audio:'+id]['id'],media['id'])
        self.assertEqual(self.client.post(f'/api/cuts/{self.cut}/confirm',json=self.command(version_id=version['id'])).status_code,200)
        raw['audio_references'][0]['segment_start_s']=1.0
        self.save(raw)
        partial=render(CompileInput.model_validate(raw),self.fake.plan,'partial').prompt
        self.assertIn('partially_copy',partial); self.assertNotIn('fully_copy',partial)

    def test_late_asr_proposal_preserves_manual_transcript_and_requires_explicit_apply(self):
        from app.assistance import Assistance
        from app.contracts import AssistanceResult
        from app.domain import Metrics
        id,_=self.audio()
        entered,release=threading.Event(),threading.Event()
        def recognize(*args):
            entered.set(); release.wait(3)
            return AssistanceResult(status='proposal',text='Una proposta.',language='Italian',
                metrics=Metrics(model='local-whisper',digest='local-v1',task='audio_asr',input_hash='test',input_chars=0,inference_calls=1,queue_s=0,wall_s=.01))
        with patch('app.transcription.status',return_value={'available':True}), patch.object(Assistance,'_asr_digest',return_value='local-v1'), patch('app.transcription.transcribe',side_effect=recognize):
            response=self.client.post(f'/api/cuts/{self.cut}/assistance',json=self.command(kind='audio_asr',target_id=id,model='local-whisper'))
            self.assertEqual(response.status_code,202,response.text)
            self.assertTrue(entered.wait(2))
            raw=self.view()['draft_input']; raw['audio_references'][0]['transcript']='La mia correzione esatta.'
            self.save(raw); release.set()
            job=self.completed(response.json())
            self.assertTrue(job['stale']); self.assertEqual(self.apply(job).status_code,409)
            self.assertEqual(self.view()['draft_input']['audio_references'][0]['transcript'],'La mia correzione esatta.')
            self.assertEqual(job['result']['metrics']['inference_calls'],1)


class AnalysisResponseTests(unittest.TestCase):
    def inference(self, response, kind='image_analyze'):
        client=Mock(keep_alive='0'); client._request.return_value=response
        result=infer(client,kind,'local-model','digest','hash',content=png(),role='identity')
        client._request.assert_called_once()
        request=client._request.call_args.args[1]
        self.assertFalse(request['think']); self.assertGreaterEqual(request['options']['num_predict'],4096)
        return result

    def test_character_sheet_rejects_layout_commentary_but_keeps_printed_words(self):
        for description, expected in [
            ('The left panel shows a woman with long hair.', 'error'),
            ('A woman with long hair wearing a pink top printed "PARIS ARCHIVE".', 'proposal'),
        ]:
            response = {'done': True, 'done_reason': 'stop',
                        'message': {'content': json.dumps({'description': description})}}
            with self.subTest(description=description):
                result = self.inference(response, 'image_character_sheet')
                self.assertEqual(result.status, expected)
                self.assertEqual(result.text, description if expected == 'proposal' else None)

    def test_incidental_sheet_views_cannot_be_applied_as_a_unified_description(self):
        for description in [
            ('A slender woman with long, straight black hair and a fair complexion. '
             'She has a neutral facial expression, dark eyes, and a straight nose. '
             'She is depicted entirely unclothed in various full-body and close-up views, '
             'showing her lean build and natural features.'),
            'A person with short brown hair and round glasses, depicted in various full-body and close-up views.',
            'A person wears a green jacket. The person is shown in different views.',
            'A person with curly hair and blue eyes seen in side views.',
        ]:
            with self.subTest(description=description):
                result=self.inference(dict(done=True,done_reason='stop',message=dict(content=json.dumps(dict(description=description)))),'image_character_sheet')
                self.assertEqual(result.status,'error');self.assertIsNone(result.text)
                self.assertEqual(result.warnings,[])
                self.assertEqual(result.metrics.error_code,'sheet_layout_description')

    def test_sheet_layout_or_view_led_sentences_remain_errors_without_partial_text(self):
        for description in ['A collage shows a person.', 'The left panel shows a person.',
                            'The front view shows a person with glasses.', 'In the side view a person stands.',
                            'Front, side, and back views show the same person.',
                            'A person has short hair. The side view shows a coat.',
                            'Different views of the same person are arranged in a row.',
                            'A person with dark hair appears in the upper-left portrait.',
                            'The sheet shows a person with round glasses.',
                            'A man wears a green jacket. Three panels depict his outfit.',
                            'A woman has red hair, with close-ups of her hands below.',
                            'A woman wears a blue jacket in one panel.',
                            'Panel A depicts the same woman from the front.',
                            'The panels show a woman with short hair.']:
            with self.subTest(description=description):
                result=self.inference(dict(done=True,done_reason='stop',message=dict(content=json.dumps(dict(description=description)))),'image_character_sheet')
                self.assertEqual(result.status,'error');self.assertIsNone(result.text)
                self.assertEqual(result.metrics.error_code,'sheet_layout_description');self.assertEqual(result.warnings,[])

    def test_quoted_lettering_and_ordinary_image_analysis_have_no_sheet_warning(self):
        for kind,description in [('image_character_sheet','A person wears a T-shirt printed "CLOSE-UP VIEWS".'),
                                 ('image_analyze','A person is visible in multiple views.')]:
            result=self.inference(dict(done=True,done_reason='stop',message=dict(content=json.dumps(dict(description=description)))),kind)
            self.assertEqual(result.status,'proposal');self.assertEqual(result.text,description)
            self.assertEqual(result.warnings,[]);self.assertNotIn('warnings',result.model_dump())

    def test_unified_sheet_description_keeps_anatomical_and_garment_locations(self):
        for lettering in ['"FRONT VIEW"', "'FRONT VIEW'", '“FRONT VIEW”', '‘FRONT VIEW’']:
            description=(f'A woman with short curly hair wears a green jacket with {lettering} printed on its back. '
                         'The front panel of her jacket has a narrow zip and her left forearm has a small scar.')
            with self.subTest(lettering=lettering):
                result=self.inference(dict(done=True,done_reason='stop',message=dict(content=json.dumps(dict(description=description)))),'image_character_sheet')
                self.assertEqual(result.status,'proposal');self.assertEqual(result.text,description)
                self.assertEqual(result.warnings,[])

    def test_old_assistance_results_keep_empty_warning_defaults_omitted(self):
        from app.contracts import AssistanceResult
        old=dict(status='proposal',text='A person with a green jacket.',language='English',recognized=None,issues=[],metrics=None)
        self.assertEqual(AssistanceResult.model_validate(old).model_dump(),old)

    def test_thinking_only_at_limit_is_reported_without_exposing_or_reusing_it(self):
        result=self.inference({'done':True,'done_reason':'length','eval_count':2048,
            'message':{'content':'','thinking':'PRIVATE_REASONING'}})
        self.assertEqual(result.status,'error'); self.assertIsNone(result.text)
        self.assertEqual(result.metrics.error_code,'thinking_budget_exhausted')
        self.assertEqual(result.metrics.inference_calls,1); self.assertEqual(result.metrics.output_tokens,2048)
        self.assertIn('ragionamento interno',result.issues[0])
        self.assertNotIn('PRIVATE_REASONING',result.model_dump_json())

    def test_truncated_content_is_never_accepted_even_if_json_is_parseable(self):
        result=self.inference({'done':True,'done_reason':'length','eval_count':2048,
            'message':{'content':'{"description":"partial description"}'}})
        self.assertEqual(result.metrics.error_code,'truncated_response'); self.assertIsNone(result.text)
        self.assertIn('limite di output',result.issues[0])

    def test_complete_answer_after_thinking_uses_only_final_description(self):
        result=self.inference({'done':True,'done_reason':'stop','eval_count':900,
            'message':{'content':'{"description":"A woman with long brown hair."}','thinking':'PRIVATE_REASONING'}})
        self.assertEqual(result.status,'proposal'); self.assertEqual(result.text,'A woman with long brown hair.')
        self.assertEqual(result.metrics.output_tokens,900); self.assertNotIn('PRIVATE_REASONING',result.model_dump_json())

    def test_invalid_response_has_distinct_message_and_no_retry(self):
        for content in ['not json',None]:
            with self.subTest(content=content):
                result=self.inference({'done':True,'done_reason':'stop','message':{'content':content}})
                self.assertEqual(result.metrics.error_code,'invalid_response'); self.assertIsNone(result.text)
                self.assertIn('formato',result.issues[0])


class AudioDomainTests(unittest.TestCase):
    def audio(self, **changes):
        return {'id':'a1','slot':1,'media_id':'managed','measured_duration_s':5.0,'sample_rate':8000,'sample_count':40000,'channels':1,
                'speaker_subject':1,'transcript':'  Ciao!  ','confirmed':True,'linked_to_h3':True,**changes}
    def test_file_dialogue_exact_words_speaker_and_terminator(self):
        raw=catalogue_input(); raw['audio_references']=[self.audio()]
        raw['request']='<Subject 1> pronuncia il contenuto di <Audio 1>.'
        data=CompileInput.model_validate(raw)
        plan=Interpretation(narrative_en='{{dialogue:a1}} <Subject 1> looks up.',estimated_duration_s=4.0,question=None)
        result=render(data,plan,input_hash(data))
        self.assertIn('<Subject 1> (S1) says: <d>[Italian]   Ciao!  </d>.',result.prompt)
        self.assertEqual(result.duration_s,5); self.assertEqual(result.duration_origin,'measured')
        tied=render(data,plan.model_copy(update={'estimated_duration_s':5.0}),input_hash(data))
        self.assertEqual(tied.duration_origin,'measured')
        context=model_context(data)
        self.assertEqual(context['dialogues'][0]['id'],'a1'); self.assertNotIn('Ciao!',json.dumps(context))
    def test_long_audio_needs_real_segment_and_declared_duration_must_fit(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError): AudioReference.model_validate(self.audio(measured_duration_s=25.0,sample_count=200000))
        audio=AudioReference.model_validate(self.audio(measured_duration_s=25.0,sample_count=200000,segment_start_s=10.0,segment_end_s=15.0))
        self.assertEqual(audio.useful_duration_s,5)
        raw=catalogue_input(); raw['audio_references']=[audio.model_dump()]; raw['declared_duration_s']=4.0
        with self.assertRaises(ValidationError): CompileInput.model_validate(raw)
    def test_other_language_requires_explicit_consent_and_original_is_preserved(self):
        from pydantic import ValidationError
        raw=catalogue_input(); raw['pictures'][1].update(description_language='Italian',description_en='gonna blu')
        with self.assertRaises(ValidationError): CompileInput.model_validate(raw)
        raw['pictures'][1]['use_original_language']=True
        self.assertIn('gonna blu',render(CompileInput.model_validate(raw),Interpretation(narrative_en='<Subject 1> walks.',estimated_duration_s=5.0,question=None),'original').prompt)

    def test_voice_reference_does_not_emit_source_words_or_an_extra_speech_event(self):
        raw=catalogue_input(); raw['audio_references']=[self.audio(role='voice',mode='reference',transcript='SOURCE WORDS EXCLUDED')]
        raw['dialogues']=[{'id':'d1','text':'Parole nuove.','language':'Italian','speaker_subject':1,'confirmed':True}]
        data=CompileInput.model_validate(raw)
        prompt=render(data,Interpretation(narrative_en='{{dialogue:d1}}',estimated_duration_s=5.0,question=None),'voice').prompt
        self.assertNotIn('SOURCE WORDS EXCLUDED',prompt); self.assertEqual(prompt.count('<d>'),1)
        self.assertIn('voice-timbre reference',prompt); self.assertIn('reference - supplied voice',prompt)

    def test_m3_upgrade_backs_up_m2_without_rewriting_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            repo=Repository(directory)
            with closing(repo.connect()) as db: db.execute("UPDATE settings SET value='2' WHERE key='schema_version'")
            before=repo.workspace()
            reopened=Repository(directory)
            self.assertEqual(reopened.workspace(),before)
            backup=Path(directory)/'workspace.before-m3.sqlite3'
            self.assertTrue(backup.is_file())
            with closing(sqlite3.connect(backup)) as db:
                self.assertEqual(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0],'2')
            with closing(reopened.connect()) as db:
                self.assertEqual(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0],'8')


if __name__=='__main__': unittest.main()
