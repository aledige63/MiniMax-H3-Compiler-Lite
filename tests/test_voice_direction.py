import json
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.compiler import StructuralError, render
from app.domain import CompileInput, CurrentInterpretation
from app.interpreter import OllamaClient, model_context
from app.narrative import response_schema
from test_m0 import data


class VoiceDirectionTests(unittest.TestCase):
    def inputs(self, role='speech', **extra):
        raw = data().model_dump()
        raw['audio_references'] = [dict(id='a8', slot=2, name='Voce Anna', media_id='fixture', mode='reference',
            role=role, measured_duration_s=2.0, sample_rate=8000, sample_count=16000, channels=1,
            speaker_subject=1, language='Italian', transcript='  Parole da file!  ', confirmed=True, linked_to_h3=True,
            voice_emotion='angry', voice_mode='shouting', voice_tone='con rabbia trattenuta', **extra)]
        return raw

    def plan(self, narrative, tones=None):
        return CurrentInterpretation(narrative_en=narrative, summary_en='<Subject 1> speaks.',
            voice_tones_en=tones, estimated_duration_s=8.0, question=None)

    def test_reference_speech_inserts_fixed_and_translated_directions_in_its_own_line(self):
        inputs = CompileInput.model_validate(self.inputs())
        plan = self.plan('{{dialogue:d1}} {{dialogue:a8:off_screen:2}}', {'a8':'with barely controlled anger'})
        prompt = render(inputs, plan, 'reference-style').prompt
        detailed = prompt.split('detailed_description:\n')[1].split('\n\noverall_soundscape:')[0]
        self.assertIn('<Subject 1> (S1) says: <d>[Italian] Sono pronta.</d>.', detailed)
        self.assertIn('says in an off-screen voiceover, in an angry tone, shouting, with barely controlled anger: '
                      '<d>[Italian]   Parole da file!  </d>.', detailed)
        self.assertEqual(detailed.count('with barely controlled anger'), 1)
        self.assertIn('<Subject 2> listens with lips completely closed', detailed)
        self.assertNotIn('[angry]', prompt)

    def test_timbre_reference_applies_to_every_line_of_the_assigned_subject(self):
        raw = self.inputs(role='voice')
        original = raw['dialogues'][0]
        raw['dialogues'] += [dict(original, id='d2', delivery='off_screen', text='Un momento.'),
                             dict(original, id='d3', delivery='narrator', speaker_subject=None, text='Era tardi.')]
        prompt = render(CompileInput.model_validate(raw),
            self.plan('{{dialogue:d1}} {{dialogue:d3}} {{dialogue:d2}}', {'a8':'with barely controlled anger'}), 'voice-style').prompt
        self.assertEqual(prompt.count('in an angry tone, shouting, with barely controlled anger:'), 2)
        self.assertIn('An unseen narrator (S2) says in an off-screen voiceover: <d>[Italian] Era tardi.</d>.', prompt)
        self.assertNotIn('Parole da file!', prompt)

    def test_menus_require_no_translation_and_copy_keeps_original_delivery(self):
        raw = self.inputs()
        raw['audio_references'][0]['voice_tone'] = ''
        inputs = CompileInput.model_validate(raw)
        prompt = render(inputs, self.plan('{{dialogue:d1}} {{dialogue:a8}}'), 'fixed-style').prompt
        self.assertIn('says, in an angry tone, shouting: <d>[Italian]   Parole da file!  </d>.', prompt)
        self.assertEqual(response_schema(inputs)['anyOf'][0]['properties']['voice_tones_en'], {'type':'null'})
        raw['audio_references'][0]['mode'] = 'copy'
        raw['audio_references'][0]['voice_tone'] = 'con rabbia trattenuta'
        prompt = render(CompileInput.model_validate(raw), self.plan('{{dialogue:d1}} {{dialogue:a8}}'), 'copy-style').prompt
        self.assertNotIn('in an angry tone', prompt)
        self.assertIn('preserving its original voice, words, timing and delivery', prompt)

    def test_translation_is_required_in_the_same_model_call_and_omissions_are_diagnosed(self):
        inputs = CompileInput.model_validate(self.inputs())
        context = model_context(inputs)
        self.assertEqual(context['voice_tones_to_translate'], {'a8':'con rabbia trattenuta'})
        self.assertNotIn('Parole da file!', json.dumps(context))
        schema = response_schema(inputs)['anyOf'][0]['properties']['voice_tones_en']
        self.assertEqual(schema['required'], ['a8'])
        self.assertFalse(schema['additionalProperties'])
        wire = dict(narrative_parts=[{'dialogue_id':'d1'}, {'dialogue_id':'a8'}],
            summary_en='<Subject 1> speaks.', estimated_duration_s=8.0, question=None)
        client = OllamaClient()
        for tones, expected in [(None, 'manca la traduzione'), ({'a8':'[angry]'}, 'breve espressione')]:
            response = dict(done=True, done_reason='stop', message=dict(content=json.dumps(wire | {'voice_tones_en':tones})))
            with patch.object(client, '_request', side_effect=[{'models':[{'name':'test','digest':'fixture'}]}, response]):
                result = client.compile(inputs, 'test')
            self.assertEqual(result.error_code, 'invalid_structure')
            self.assertIn(expected, result.issues[0])
            self.assertEqual(result.metrics.inference_calls, 1)
        response['message']['content'] = json.dumps(wire | {'voice_tones_en':{'a8':'with barely controlled anger'}})
        with patch.object(client, '_request', side_effect=[{'models':[{'name':'test','digest':'fixture'}]}, response]):
            result = client.compile(inputs, 'test')
        self.assertEqual(result.status, 'proposal')
        self.assertIn('says, in an angry tone, shouting, with barely controlled anger:', result.prompt)
        self.assertEqual(result.interpretation.voice_tones_en, {'a8':'with barely controlled anger'})

    def test_empty_fields_preserve_legacy_hashes_and_invalid_choices_are_rejected(self):
        raw = self.inputs()
        audio = raw['audio_references'][0]
        for key in ('voice_tone', 'voice_emotion', 'voice_mode'):
            audio.pop(key)
        before = CompileInput.model_validate(raw).model_dump_json()
        audio.update(voice_tone='', voice_emotion='', voice_mode='')
        self.assertEqual(CompileInput.model_validate(raw).model_dump_json(), before)
        audio['voice_emotion'] = 'unknown'
        with self.assertRaises(ValidationError):
            CompileInput.model_validate(raw)

    def test_native_line_overrides_the_reference_and_other_lines_keep_the_default(self):
        raw = self.inputs(role='voice')
        original = dict(raw['dialogues'][0])
        raw['dialogues'][0].update(voice_emotion='happy', voice_mode='whispering', voice_tone='con dolcezza')
        raw['dialogues'].append(dict(original, id='d2', text='Aspetta.'))
        inputs = CompileInput.model_validate(raw)
        self.assertEqual(model_context(inputs)['voice_tones_to_translate'], {'d1':'con dolcezza', 'a8':'con rabbia trattenuta'})
        prompt = render(inputs, self.plan('{{dialogue:d1}} {{dialogue:d2}}',
            {'d1':'gently', 'a8':'with barely controlled anger'}), 'native-override').prompt
        self.assertIn('says, in a happy tone, whispering, gently: <d>[Italian] Sono pronta.</d>.', prompt)
        self.assertIn('says, in an angry tone, shouting, with barely controlled anger: <d>[Italian] Aspetta.</d>.', prompt)
        raw['dialogues'].pop()
        self.assertEqual(model_context(CompileInput.model_validate(raw))['voice_tones_to_translate'], {'d1':'con dolcezza'})

    def test_native_narration_has_its_own_voice_direction_without_an_audio_file(self):
        raw = data().model_dump()
        raw['dialogues'][0].update(delivery='narrator', speaker_subject=None, narrator_voice='female',
                                  voice_emotion='sad', voice_mode='soft', voice_tone='con commozione')
        inputs = CompileInput.model_validate(raw)
        self.assertEqual(response_schema(inputs)['anyOf'][0]['properties']['voice_tones_en']['required'], ['d1'])
        prompt = render(inputs, self.plan('{{dialogue:d1}}', {'d1':'with emotion'}), 'native-narrator').prompt
        self.assertIn('An unseen narrator with a female voice (S1) says in an off-screen voiceover, '
                      'in a sad tone, in a soft voice, with emotion: <d>[Italian] Sono pronta.</d>.', prompt)
        with self.assertRaisesRegex(StructuralError, 'Battuta d1'):
            render(inputs, self.plan('{{dialogue:d1}}'), 'missing-native-tone')
