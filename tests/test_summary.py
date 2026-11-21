import json
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.compiler import StructuralError, render
from app.domain import CompileInput, CompileResult, CurrentInterpretation, Interpretation
from app.interpreter import OllamaClient
from test_m0 import data, plan, structured_plan


SUMMARY = '<Subject 1> speaks from the sofa as <Subject 2> enters and stops beside <Subject 1>.'


class SummaryTests(unittest.TestCase):
    def test_action_summary_is_separate_from_detailed_playback_and_verbatim_dialogue(self):
        current = plan().model_copy(update={'summary_en': SUMMARY})
        prompt = render(data(), current, 'summary').prompt
        summary = prompt.split('summary:\n')[1].split('\n\nretention_analysis:')[0]
        self.assertEqual(summary, '[reference generation] ' + SUMMARY)
        self.assertNotIn('Active references:', summary)
        self.assertNotIn('<d>', summary); self.assertNotIn('{{', summary)
        self.assertEqual(prompt.count('<d>[Italian] Sono pronta.</d>.'), 1)
        self.assertNotIn(SUMMARY, prompt.split('detailed_description:\n')[1])

    def test_current_model_requires_summary_but_historical_plan_remains_readable(self):
        historical = plan().model_dump(exclude={'summary_en'})
        self.assertIsNone(Interpretation.model_validate(historical).summary_en)
        for value in ['missing', None, '', '   ']:
            raw = dict(historical)
            if value != 'missing': raw['summary_en'] = value
            with self.subTest(value=value), self.assertRaises(ValidationError):
                CurrentInterpretation.model_validate(raw)
        schema = CurrentInterpretation.model_json_schema()
        self.assertIn('summary_en', schema['required'])

    def test_clarification_has_no_partial_summary(self):
        raw = dict(narrative_en=None, estimated_duration_s=None, question='Chi entra prima?', summary_en=None)
        self.assertEqual(render(data(), CurrentInterpretation(**raw), 'question').status, 'clarification_needed')
        with self.assertRaises(ValidationError):
            CurrentInterpretation(**(raw | {'summary_en': 'Someone enters.'}))

    def test_invalid_summary_tokens_dialogue_and_sections_are_rejected(self):
        for text in ['<Subject 99> enters.', '<Audio 1> plays.', '<Video 1> continues.',
                     '{{dialogue:d1}}', '<d>Words</d>', 'First.\nSecond.', '[Shot 1] Someone walks.',
                     '[reference generation] Someone walks.', '(S1) speaks.', 'summary: Someone walks.',
                     'Anna speaks.']:
            with self.subTest(text=text), self.assertRaises(StructuralError):
                render(data(), plan().model_copy(update={'summary_en': text}), 'invalid')

    def test_summary_without_references_describes_action_without_invented_continuity(self):
        current = CurrentInterpretation(narrative_en='An empty room remains still.',
            summary_en='An empty room remains still.', estimated_duration_s=4.0, question=None)
        prompt = render(CompileInput(request='Una stanza vuota e immobile.'), current, 'empty').prompt
        self.assertIn('summary:\nAn empty room remains still.', prompt)
        self.assertNotIn('continuation', prompt)

    def test_summary_failure_identifies_the_exact_category_without_exposing_model_prose(self):
        cases=[('<Subject 99> enters.','riferimento non disponibile'),
               ('<private_arbitrary_tag> private prose','tag non valido'),
               ('<Subject 1 enters.','formato incompleti'),
               ('First.\nSecond.','più righe'),
               ('{{dialogue:d1}}','dialogo'),
               ('<d>private words</d>','dialogo'),
               ('{invalid}','parentesi graffe'),
               ('[Shot 1] Private prose.','marcatori di shot'),
               ('(S1) Private prose.','marcatori di shot'),
               ('[reference generation] Private prose.','prefisso'),
               ('summary: Private prose.','intestazioni'),
               ('Anna walks.','nome del personaggio')]
        for summary,reason in cases:
            with self.subTest(summary=summary),self.assertRaises(StructuralError) as error:
                render(data(),plan().model_copy(update={'summary_en':summary}),'diagnostic')
            self.assertIn(reason,str(error.exception));self.assertNotIn('private',str(error.exception).lower());self.assertNotIn('arbitrary',str(error.exception))

    def test_summary_failure_keeps_specific_reason_in_result_and_does_not_retry(self):
        raw=structured_plan()|{'summary_en':'Anna walks.'}
        response=dict(done=True,done_reason='stop',message={'content':json.dumps(raw)})
        client=OllamaClient()
        with patch.object(client,'_request',side_effect=[{'models':[{'name':'local','digest':'test'}]},response]) as request:
            result=client.compile(data(),'local')
        self.assertEqual(result.error_code,'invalid_structure');self.assertIn('nome del personaggio',result.issues[0])
        self.assertIsNone(result.prompt);self.assertFalse(result.confirmation_allowed);self.assertEqual(result.metrics.inference_calls,1);self.assertEqual(request.call_count,2)

    def test_mixed_audio_modes_keep_both_actual_task_types(self):
        raw = data().model_dump()
        base = dict(media_id='managed-file', measured_duration_s=5.0, sample_rate=8000,
                    sample_count=40000, channels=1, confirmed=True, linked_to_h3=True)
        raw['audio_references'] = [base | dict(id='a1', slot=1, role='sound', mode='copy', description_en='room tone'),
                                  base | dict(id='a2', slot=2, role='voice', mode='reference', speaker_subject=1)]
        current = plan().model_copy(update={'summary_en': SUMMARY + ' <Audio 1> supplies room tone; <Audio 2> guides the voice timbre.'})
        prompt = render(CompileInput.model_validate(raw), current, 'mixed').prompt
        self.assertIn('summary:\n[reference generation + audio reuse + audio reference] ' + SUMMARY, prompt)
        with self.assertRaises(StructuralError):
            render(CompileInput.model_validate(raw), current.model_copy(update={
                'narrative_en': '<Subject 1> looks at the camera and {{dialogue:d1}} with the timbre of <Audio 2>.'}), 'mixed-invalid')

    def test_same_inference_produces_summary_without_sending_dialogue_words(self):
        raw = structured_plan() | {'summary_en': SUMMARY}
        response = dict(done=True, done_reason='stop', message={'content': json.dumps(raw)})
        client = OllamaClient()
        with patch.object(client, '_request', side_effect=[{'models': [{'name': 'local', 'digest': 'test'}]}, response]) as request:
            result = client.compile(data(), 'local')
        self.assertEqual(result.status, 'proposal'); self.assertEqual(result.interpretation.summary_en, SUMMARY)
        self.assertEqual(result.metrics.inference_calls, 1); self.assertEqual(request.call_count, 2)
        self.assertIn('summary_en', request.call_args.args[1]['format']['anyOf'][0]['required'])
        self.assertNotIn('Sono pronta.', json.dumps(request.call_args.args[1]))

    def test_missing_summary_in_new_response_fails_without_retry(self):
        raw = structured_plan()
        client = OllamaClient()
        with patch.object(client, '_request', side_effect=[{'models': [{'name': 'local', 'digest': 'test'}]},
                         dict(done=True, done_reason='stop', message={'content': json.dumps(raw)})]) as request:
            result = client.compile(data(), 'local')
        self.assertEqual(result.status, 'error'); self.assertEqual(result.error_code, 'missing_essential_data')
        self.assertEqual(request.call_count, 2)

    def test_old_compile_result_keeps_its_exact_text(self):
        raw = render(data(), plan(), 'old').model_dump()
        raw['interpretation'].pop('summary_en')
        previous = raw['prompt']
        result = CompileResult.model_validate(raw)
        self.assertEqual(result.prompt, previous); self.assertIsNone(result.interpretation.summary_en)


if __name__ == '__main__': unittest.main()
