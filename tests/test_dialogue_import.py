import copy
import json
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api import create_app
from app.dialogue_import import quoted_speech
from app.domain import CompileInput,CurrentInterpretation
from app.interpreter import OllamaClient
from test_api import FakeOllama

REQUEST='<Subject 1> si volta e dice: "  Forse... provo questo.  " Guarda la vetrina ed aggiunge «Questo lo compro!» e si volta a sinistra.'


class DialogueImportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.fake=FakeOllama();self.app=create_app(self.temp.name,self.fake)
        self.client=TestClient(self.app,base_url='http://127.0.0.1:8767');self.client.__enter__();self.cut=self.client.get('/api/workspace').json()['id']
        for kind in ['picture','unit']:self.client.post(f'/api/cuts/{self.cut}/items',json=self.command(kind=kind))
        raw=self.view()['draft_input'];p=raw['pictures'][0];p.update(description_en='a woman with brown hair',confirmed=True,linked_to_h3=True)
        raw['active_units'][0].update(name='Ann',description_en='Ann',confirmed=True,sources=[dict(picture_id=p['id'],attribute='identity')])
        raw.update(request=REQUEST,declared_duration_s=10.0);self.save(raw)
    def tearDown(self):self.client.__exit__(None,None,None);self.temp.cleanup()
    def view(self):return self.client.get(f'/api/cuts/{self.cut}').json()
    def command(self,**extra):return dict(command_id=str(uuid4()),expected_revision=self.view()['revision'],**extra)
    def save(self,raw):return self.client.put(f'/api/cuts/{self.cut}/draft',json=self.command(input=raw))
    def preview(self):return self.client.get(f'/api/cuts/{self.cut}/dialogues/preview').json()
    def payload(self):
        p=self.preview();return dict(command_id=str(uuid4()),expected_revision=p['revision'],source_request=p['source_request'],confirmed=True,
            dialogues=[dict(index=c['index'],text=c['text'],language='Italian',speaker_subject=1) for c in p['candidates']])
    def apply(self,payload):return self.client.post(f'/api/cuts/{self.cut}/dialogues/import',json=payload)

    def test_preview_is_read_only_and_preserves_quote_content(self):
        before=self.view();p=self.preview()
        self.assertEqual([c['text'] for c in p['candidates']],['  Forse... provo questo.  ','Questo lo compro!'])
        self.assertEqual(before,self.view());self.assertEqual(self.fake.calls,0)
        self.assertEqual(quoted_speech('La vetrina riporta la scritta "Sconti".'),[])
        self.assertEqual(quoted_speech('<Subject 1> sussurra “Non dirlo.”')[0]['text'],'Non dirlo.')

    def test_import_is_atomic_verbatim_idempotent_and_has_no_inference(self):
        payload=self.payload();response=self.apply(payload);self.assertEqual(response.status_code,200,response.text)
        view=response.json();raw=view['draft_input'];self.assertEqual([d['id'] for d in raw['dialogues']],['d1','d2'])
        self.assertEqual([d['text'] for d in raw['dialogues']],['  Forse... provo questo.  ','Questo lo compro!'])
        self.assertEqual(raw['request'],'<Subject 1> si volta e pronuncia la battuta d1 Guarda la vetrina ed pronuncia la battuta d2 e si volta a sinistra.')
        self.assertEqual(self.apply(payload).json(),view);self.assertEqual(self.fake.calls,0)
        self.assertEqual(raw['pictures'],self.view()['draft_input']['pictures'])
        self.assertTrue(all(d['confirmed'] for d in raw['dialogues']))
        data=CompileInput.model_validate(raw)
        from app.compiler import render
        plan=CurrentInterpretation(narrative_en='<Subject 1> turns. {{dialogue:d1}} <Subject 1> looks toward the shop window. {{dialogue:d2}} <Subject 1> turns left.',summary_en='<Subject 1> speaks and turns toward the shop.',estimated_duration_s=10.0,question=None)
        prompt=render(data,plan,'test').prompt
        self.assertIn('<d>[Italian]   Forse... provo questo.  </d>.',prompt);self.assertIn('<d>[Italian] Questo lo compro!</d>.',prompt)

    def test_invalid_selection_speaker_or_unconfirmed_import_changes_nothing(self):
        for change in ['duplicate','unknown','speaker','empty','unconfirmed','source']:
            payload=self.payload();before=self.view()
            if change=='duplicate':payload['dialogues'].append(copy.deepcopy(payload['dialogues'][0]))
            if change=='unknown':payload['dialogues'][0]['index']=99
            if change=='speaker':payload['dialogues'][0]['speaker_subject']=99
            if change=='empty':payload['dialogues'][1]['text']=' '
            if change=='unconfirmed':payload['confirmed']=False
            if change=='source':payload['source_request']+=' altered'
            response=self.apply(payload)
            self.assertIn(response.status_code,[409,422],response.text);self.assertEqual(self.view(),before)

    def test_import_reuses_numbers_after_all_dialogues_have_been_removed(self):
        self.assertEqual(self.apply(self.payload()).status_code, 200)
        raw = self.view()['draft_input']
        raw.update(request=REQUEST, dialogues=[])
        self.assertEqual(self.save(raw).status_code, 200)
        imported = self.apply(self.payload())
        self.assertEqual(imported.status_code, 200, imported.text)
        self.assertEqual([line['id'] for line in imported.json()['draft_input']['dialogues']], ['d1', 'd2'])
        self.assertEqual(self.fake.calls, 0)

    def test_edited_request_revision_conflicts_and_existing_dialogues_do_not_duplicate(self):
        payload=self.payload();raw=self.view()['draft_input'];raw['request']+=' Poi entra.';self.save(raw)
        self.assertEqual(self.apply(payload).status_code,409)
        self.assertEqual(self.apply(self.payload()).status_code,200)
        after=self.view();again=self.payload();self.assertEqual(self.apply(again).status_code,422);self.assertEqual(self.view(),after)

    def test_selection_can_exclude_a_written_quote_and_edits_are_explicit(self):
        payload=self.payload();payload['dialogues']=payload['dialogues'][:1];payload['dialogues'][0]['text']='Testo corretto da me.'
        response=self.apply(payload);self.assertEqual(response.status_code,200,response.text)
        raw=response.json()['draft_input'];self.assertIn('aggiunge «Questo lo compro!»',raw['request'])
        self.assertEqual(raw['dialogues'][0]['text'],'Testo corretto da me.')

    def test_import_narrator_without_subject_preserves_mode_and_replay(self):
        raw = self.view()['draft_input']
        raw.update(active_units=[], request='Piove sulla strada. Una voce narrante dice: «Era tardi.»')
        self.assertEqual(self.save(raw).status_code, 200)
        payload = self.payload()
        payload['dialogues'][0].update(delivery='narrator', speaker_subject=None, narrator_voice='female')
        response = self.apply(payload)
        self.assertEqual(response.status_code, 200, response.text)
        view = response.json()
        stored = CompileInput.model_validate(view['draft_input']).dialogues[0]
        self.assertEqual((stored.delivery, stored.speaker_subject, stored.text), ('narrator', None, 'Era tardi.'))
        self.assertEqual(stored.narrator_voice, 'female')
        self.assertEqual(self.apply(payload).json(), view)
        self.assertEqual(self.fake.calls, 0)

    def test_renderer_error_is_explained_without_exposing_model_output_or_retry(self):
        raw=self.view()['draft_input'];data=CompileInput.model_validate(raw);client=OllamaClient()
        reply=dict(done=True,done_reason='stop',message=dict(content=json.dumps(dict(narrative_parts=[dict(dialogue_id='d1')],summary_en='<Subject 1> speaks.',estimated_duration_s=10.0,question=None))))
        with patch.object(client,'_request',side_effect=[{'models':[dict(name='local',digest='test')]},reply]) as call:
            result=client.compile(data,'local')
        self.assertEqual(result.error_code,'invalid_structure');self.assertIn('Recupera battute',result.issues[0]);self.assertNotIn('{{dialogue',result.issues[0])
        self.assertEqual(call.call_count,2);self.assertEqual(result.metrics.inference_calls,1)
