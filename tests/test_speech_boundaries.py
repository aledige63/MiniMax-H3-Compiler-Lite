import json
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.compiler import StructuralError, render
from app.domain import CompileInput, CompileResult, CurrentInterpretation, Dialogue
from app.interpreter import OllamaClient, model_context
from test_m0 import data


class SpeechBoundaryTests(unittest.TestCase):
    def test_missing_or_repeated_speech_identifies_native_id_or_audio_slot_without_model_prose(self):
        raw = data().model_dump()
        raw['audio_references'] = [dict(id='a8', slot=2, name='Mamma', media_id='fixture', role='speech', mode='copy',
            measured_duration_s=2.0, sample_rate=8000, sample_count=16000, channels=1, speaker_subject=1,
            transcript='Testo verificato.', confirmed=True, linked_to_h3=True)]
        inputs = CompileInput.model_validate(raw)
        cases = [
            ('{{dialogue:a8}}', 'ha omesso: Battuta d1 (Subject 1)'),
            ('{{dialogue:d1}}', 'ha omesso: Audio 2 · Mamma (Subject 1)'),
            ('{{dialogue:d1}} {{dialogue:a8}} {{dialogue:a8}}', 'ha ripetuto: Audio 2 · Mamma (Subject 1) (2 occorrenze)'),
            ('{{dialogue:d1}} {{dialogue:a8}} {{dialogue:private_model_label}}', 'aggiunto battute non registrate'),
        ]
        for narrative, expected in cases:
            plan = CurrentInterpretation(narrative_en=narrative, summary_en='<Subject 1> speaks.', estimated_duration_s=8.0, question=None)
            with self.subTest(narrative=narrative), self.assertRaises(StructuralError) as caught:
                render(inputs, plan, 'speech-count-diagnostics')
            message = str(caught.exception)
            self.assertIn(expected, message)
            self.assertNotIn('private_model_label', message)
            self.assertNotIn('{{dialogue', message)
            self.assertIn('battute da conservare', message)

    def test_unfinished_speech_names_native_dialogue_or_narrator_without_model_prose(self):
        for delivery in ['on_screen', 'off_screen', 'narrator']:
            raw = data().model_dump()
            raw['dialogues'][0]['delivery'] = delivery
            if delivery == 'narrator':
                raw['dialogues'][0]['speaker_subject'] = None
            inputs = CompileInput.model_validate(raw)
            plan = CurrentInterpretation(narrative_en='PRIVATE_MODEL_PROSE says: {{dialogue:d1}}',
                summary_en='A voice speaks.', estimated_duration_s=5.0, question=None)
            with self.subTest(delivery=delivery), self.assertRaises(StructuralError) as caught:
                render(inputs, plan, 'unfinished-speech')
            message = str(caught.exception)
            self.assertIn('Battuta d1', message)
            self.assertIn('voce narrante' if delivery == 'narrator' else 'Subject 1', message)
            self.assertIn('ricompila', message)
            self.assertNotIn('PRIVATE_MODEL_PROSE', message)
            self.assertNotIn('{{dialogue', message)

    def test_audio_sentence_error_names_slot_and_speaker_without_retry_or_changing_words(self):
        raw = data().model_dump()
        raw['dialogues'] = []
        raw['active_units'].append(dict(raw['active_units'][0], subject=4, name='Mamma'))
        audio = dict(media_id='fixture', role='speech', mode='copy', measured_duration_s=2.0,
            sample_rate=8000, sample_count=16000, channels=1, language='Italian', confirmed=True, linked_to_h3=True)
        raw['audio_references'] = [dict(audio, id='a8', slot=2, name='Mamma', speaker_subject=4, transcript='  Chi sei?  '),
                                   dict(audio, id='a9', slot=1, name='Anna', speaker_subject=1, transcript='Sono io!')]
        inputs = CompileInput.model_validate(raw)
        entries = model_context(inputs)['dialogues']
        self.assertEqual([(d['audio'], d['placeholder']) for d in entries],
            [('<Audio 2>', '{{dialogue:a8}}'), ('<Audio 1>', '{{dialogue:a9}}')])
        self.assertNotIn('Chi sei?', json.dumps(model_context(inputs)))
        client = OllamaClient()
        bad = dict(narrative_en='PRIVATE_MODEL_PROSE <Subject 4> says: {{dialogue:a8}} {{dialogue:a9}}',
            summary_en='<Subject 4> and <Subject 1> exchange words.', estimated_duration_s=8.0, question=None)
        wire = dict(narrative_parts=[dict(action_en='PRIVATE_MODEL_PROSE <Subject 4> says:'),
            dict(dialogue_id='a8'), dict(dialogue_id='a9')], summary_en=bad['summary_en'],
            estimated_duration_s=8.0, question=None)
        reply = dict(done=True, done_reason='stop', message=dict(content=json.dumps(wire)))
        with patch.object(client, '_request', side_effect=[{'models': [dict(name='local', digest='test')]}, reply]) as call:
            result = client.compile(inputs, 'local')
        self.assertEqual(result.error_code, 'invalid_structure')
        self.assertIn('Audio 2 · Mamma (Subject 4)', result.issues[0])
        self.assertNotIn('PRIVATE_MODEL_PROSE', result.issues[0])
        self.assertNotIn('{{dialogue', result.issues[0])
        self.assertEqual(call.call_count, 2)
        self.assertEqual(result.metrics.inference_calls, 1)
        good = CurrentInterpretation(**dict(bad, narrative_en='{{dialogue:a8}} <Subject 1> looks left. {{dialogue:a9}}'))
        prompt = render(inputs, good, 'separate-audio-speech').prompt
        self.assertIn('<Subject 4> (S1) says: <d>[Italian]   Chi sei?  </d>.', prompt)
        self.assertIn('<Subject 1> (S2) says: <d>[Italian] Sono io!</d>.', prompt)
        self.assertEqual(prompt.count('</d>.'), 2)

    def test_three_deliveries_use_stable_speakers_and_exact_terminators(self):
        raw = data().model_dump()
        original = raw['dialogues'][0]
        raw['dialogues'] = [
            original,
            dict(original, id='d2', delivery='off_screen', text='  Aspetta!  '),
            dict(original, id='d3', delivery='narrator', speaker_subject=None, text='Era tardi.'),
            dict(original, id='d4', delivery='narrator', speaker_subject=None, text='Pioveva.'),
        ]
        inputs = CompileInput.model_validate(raw)
        plan = CurrentInterpretation(
            narrative_en='{{dialogue:d3}}. {{dialogue:d1}} {{dialogue:d2}} {{dialogue:d4}}',
            summary_en='An unseen narrator sets the scene as <Subject 1> speaks.',
            estimated_duration_s=9.0, question=None)
        prompt = render(inputs, plan, 'deliveries').prompt
        for line in [
            'An unseen narrator (S1) says in an off-screen voiceover: <d>[Italian] Era tardi.</d>.',
            f'<Subject 1> (S2) says: <d>[Italian] {original["text"]}</d>.',
            '<Subject 1> (S2) says in an off-screen voiceover: <d>[Italian]   Aspetta!  </d>.',
            'An unseen narrator (S1) says in an off-screen voiceover: <d>[Italian] Pioveva.</d>.',
        ]:
            self.assertIn(line, prompt)
        self.assertEqual(prompt.count('</d>.'), 4)
        self.assertNotIn('</d>..', prompt)
        self.assertIn('overall_soundscape:\nAmbient sounds.\n\n', prompt)
        context = model_context(inputs)['dialogues']
        self.assertEqual([item['delivery'] for item in context], ['on_screen', 'off_screen', 'narrator', 'narrator'])
        self.assertEqual(context[2]['speaker'], 'An unseen narrator')
        self.assertNotIn('Era tardi.', str(context))

    def test_narrator_needs_no_subject_and_default_serializes_like_legacy(self):
        original = data().model_dump()['dialogues'][0]
        self.assertEqual(Dialogue.model_validate(dict(original, delivery='on_screen')).model_dump(), original)
        for delivery, speaker in [('narrator', 1), ('off_screen', None), ('on_screen', None)]:
            with self.subTest(delivery=delivery), self.assertRaises(ValidationError):
                Dialogue.model_validate(dict(original, delivery=delivery, speaker_subject=speaker))
        inputs = CompileInput(request='Piove su una strada deserta. Usa la battuta d1.',
                              dialogues=[Dialogue.model_validate(dict(original, delivery='narrator', speaker_subject=None))])
        self.assertEqual(inputs.active_units, [])

    def test_male_and_female_narrator_voices_use_distinct_stable_ids(self):
        raw = dict(delivery='narrator', language='Italian', confirmed=True)
        inputs = CompileInput(request='Tre battute fuori campo.', dialogues=[
            Dialogue(**raw, id='d1', text='Piove.', narrator_voice='female'),
            Dialogue(**raw, id='d2', text='Lo so.', narrator_voice='male'),
            Dialogue(**raw, id='d3', text='Andiamo!', narrator_voice='female'),
        ])
        plan = CurrentInterpretation(
            narrative_en='{{dialogue:d2}} {{dialogue:d1}} {{dialogue:d3}}',
            summary_en='Two unseen voices are heard.', estimated_duration_s=6.0, question=None)
        prompt = render(inputs, plan, 'narrator-voices').prompt
        self.assertIn('An unseen narrator with a male voice (S1) says in an off-screen voiceover: <d>[Italian] Lo so.</d>.', prompt)
        for line in ('Piove.', 'Andiamo!'):
            self.assertIn(f'An unseen narrator with a female voice (S2) says in an off-screen voiceover: <d>[Italian] {line}</d>.', prompt)
        self.assertEqual(model_context(inputs)['dialogues'][0]['speaker'], 'An unseen narrator with a female voice')
        with self.assertRaises(ValidationError):
            Dialogue(id='d1', text='Piove.', language='Italian', confirmed=True,
                     speaker_subject=1, narrator_voice='female')

    def test_actions_follow_closed_verbatim_dialogue_without_an_extra_speech_layer(self):
        raw=data().model_dump();raw['dialogues'][0]['text']='  Davvero?!  '
        plan=CurrentInterpretation(narrative_en='<Subject 1> looks toward the camera. {{dialogue:d1}} Then, <Subject 1> looks toward the door.',
            summary_en='<Subject 1> speaks and then looks toward the door.',estimated_duration_s=7.0,question=None)
        for ambient in [True,False]:
            raw['ambient_sound']=ambient
            prompt=render(CompileInput.model_validate(raw),plan,'speech-boundary').prompt
            self.assertIn('<d>[Italian]   Davvero?!  </d>. Then, <Subject 1> looks toward the door.',prompt)
            soundscape=prompt.split('overall_soundscape:\n')[1].split('\n\n')[0]
            self.assertEqual(soundscape,'Ambient sounds.' if ambient else 'N/A')
            self.assertNotIn('line ends',prompt)

    def test_explicit_audio_routing_survives_without_generic_native_speech(self):
        raw=data().model_dump()
        raw['audio_references']=[dict(id='a1',slot=1,media_id='fixture',role='sound',mode='reference',
            measured_duration_s=5.0,sample_rate=8000,sample_count=40000,channels=1,description_en='street ambience',confirmed=True,linked_to_h3=True)]
        plan=CurrentInterpretation(narrative_en='{{dialogue:d1}}',summary_en='<Subject 1> speaks with street ambience referenced from <Audio 1>.',estimated_duration_s=5.0,question=None)
        prompt=render(CompileInput.model_validate(raw),plan,'explicit-audio').prompt
        self.assertIn('overall_soundscape:\nAmbient sounds. Reference <Audio 1> for supplied sound.',prompt)
        self.assertNotIn('On-screen speech',prompt);self.assertNotIn('Native on-screen',prompt)

    def test_spoken_words_and_archived_prompt_are_never_filtered_for_these_phrases(self):
        raw=data().model_dump();raw['dialogues'][0]['text']="After the line ends, say On-screen speech."
        plan=CurrentInterpretation(narrative_en='{{dialogue:d1}}',summary_en='<Subject 1> delivers a line.',estimated_duration_s=5.0,question=None)
        result=render(CompileInput.model_validate(raw),plan,'verbatim')
        self.assertIn('<d>[Italian] '+raw['dialogues'][0]['text']+'</d>.',result.prompt)
        stored=result.model_dump();stored['prompt']="OLD: After <Subject 1>'s line ends. On-screen speech."
        self.assertEqual(CompileResult.model_validate(stored).prompt,stored['prompt'])
