"""Mapping e apertura delle guide con dati sintetici, senza inferenze reali."""
import copy
import json
import unittest
from unittest.mock import patch

from app.compiler import StructuralError, render
from app.domain import CompileInput, CurrentInterpretation
from app.interpreter import OllamaClient, model_context
from app.narrative import NarrativePlan, response_schema
import test_m5 as m5


GUIDE = ('Opening: the subject mapped to the white box is partly visible on the left. '
         'The character mapped to the red mannequin is initially outside the frame.\n'
         'At 0.5s, the character enters from the right.\n'
         'From 0.0s to 4.4s, the object approaches the camera.\n'
         'From 6.0s to 8.0s, both subjects remain stationary.')


def guided_input():
    return dict(request='<Subject 5> si avvicina a <Subject 8> che arriva.', declared_duration_s=8.0,
        pictures=[dict(id='person',slot=4,role='identity',description_en='a woman in a green jacket',confirmed=True,linked_to_h3=True),
                  dict(id='car',slot=7,role='object',description_en='a blue compact car',confirmed=True,linked_to_h3=True)],
        active_units=[dict(subject=5,name='Lea',role='character',confirmed=True,sources=[dict(picture_id='person',attribute='identity')]),
                      dict(subject=8,name='Car',role='object',confirmed=True,sources=[dict(picture_id='car',attribute='object')])],
        videos=[dict(id='v3',slot=3,role='camera_and_subject_motion',description_en='the declared motion guide',
            duration_s=8.0,file_exists=True,confirmed=True,linked_to_h3=True,guidance=dict(enabled=True,
                mappings=[dict(figure=' red mannequin ',role='motion',subject=5),dict(figure='white box ',role='motion',subject=8)],
                prompt_en=GUIDE))])


def plan(narrative='{{guide:video_3}}', summary='<Subject 5> enters and approaches <Subject 8>, which arrives and stops using <Video 3>.'):
    return CurrentInterpretation(narrative_en=narrative, summary_en=summary, estimated_duration_s=8.0, question=None)


class MotionGuideTests(unittest.TestCase):
    def test_definitions_separate_appearance_and_motion_for_character_and_object(self):
        raw = guided_input(); before = copy.deepcopy(raw)
        data = CompileInput.model_validate(raw); snapshot = data.model_dump()
        prompt = render(data, plan(), 'new').prompt
        definitions = prompt.split('\n\nsummary:')[0]
        self.assertIn('<Subject 5> is a woman in a green jacket from <Picture 4>.', definitions)
        self.assertIn('<Subject 8> is a blue compact car from <Picture 7>.', definitions)
        self.assertIn('motion of <Subject 5> follow the "red mannequin" proxy in <Video 3>', definitions)
        self.assertIn('motion of <Subject 8> follow the "white box" proxy in <Video 3>', definitions)
        self.assertEqual(definitions.count(' is '), 3)  # Two Subjects and one Video, no proxy Subjects.
        self.assertEqual(raw, before)
        self.assertEqual(data.model_dump(), snapshot)

    def test_proxy_replacement_and_late_entry_are_explicit_without_rewriting_the_guide(self):
        prompt = render(CompileInput.model_validate(guided_input()), plan(), 'new').prompt
        detailed = prompt.split('detailed_description:\n')[1].split('\n\noverall_soundscape:')[0]
        self.assertEqual(detailed.count(GUIDE), 1)
        self.assertEqual(detailed.count('Opening:'), 1)
        self.assertIn('Each mapped Subject replaces its guide proxy in place', detailed)
        self.assertIn('remains outside the frame until that entry', detailed)
        self.assertIn('"white box" identifies the motion of <Subject 8>', detailed)
        self.assertNotIn('<Subject 1>', prompt)
        self.assertNotIn('<Video 1>', prompt)

    def test_model_context_identifies_guide_owned_opening_and_source_roles(self):
        context = model_context(CompileInput.model_validate(guided_input()))
        guide = context['direction_guides'][0]
        self.assertEqual(guide['verbatim_prompt_en'], GUIDE)
        self.assertEqual(guide['opening_en'], GUIDE.splitlines()[0].split(': ',1)[1])
        self.assertEqual([m['subject'] for m in guide['subject_bindings']], ['<Subject 5>','<Subject 8>'])
        self.assertEqual([m['proxy'] for m in guide['subject_bindings']], ['red mannequin','white box'])
        self.assertIn('do not add another opening', guide['opening_authority'])

    def test_second_opening_is_rejected_even_when_appended_after_the_entire_guide(self):
        data = CompileInput.model_validate(guided_input())
        for opening in ['The scene opens with <Subject 5> walking on the sidewalk.',
                        'At the opening, <Subject 5> walks toward <Subject 8>.',
                        'Initially, she walks toward the arriving car.',
                        'The first frame shows <Subject 8> arriving in the distance.']:
            with self.subTest(opening=opening), self.assertRaisesRegex(StructuralError, 'seconda apertura'):
                render(data, plan('{{guide:video_3}} '+opening), 'bad')
        with self.assertRaisesRegex(StructuralError, 'Summary:'):
            render(data, plan(summary='The scene opens with <Subject 5> already walking.'), 'bad-summary')

    def test_opening_diagnostics_do_not_rewrite_or_retry_a_failed_model_response(self):
        data = CompileInput.model_validate(guided_input())
        wire = dict(narrative_parts=[dict(guide_id='video_3'),dict(action_en='The scene opens with <Subject 5> walking.')],
            summary_en='<Subject 5> approaches <Subject 8>.',estimated_duration_s=8.0,question=None)
        response = dict(done=True,done_reason='stop',message=dict(content=json.dumps(wire)))
        def request(path, payload=None):
            return dict(models=[dict(name='fixture',digest='digest')]) if path=='/api/tags' else response
        with patch.object(OllamaClient, '_request', side_effect=request) as mocked:
            result = OllamaClient().compile(data,'fixture')
        self.assertEqual(result.status,'error')
        self.assertEqual(result.error_code,'invalid_structure')
        self.assertEqual(result.metrics.inference_calls,1)
        self.assertEqual(sum(c.args[0]=='/api/chat' for c in mocked.call_args_list),1)
        self.assertIsNone(result.prompt)

    def test_a_guide_only_narrative_is_a_complete_single_call_proposal(self):
        data = CompileInput.model_validate(guided_input())
        wire = dict(narrative_parts=[dict(guide_id='video_3')],summary_en=plan().summary_en,
                    estimated_duration_s=8.0,question=None)
        proposal = NarrativePlan.model_validate(wire)
        self.assertEqual(proposal.interpretation().narrative_en,'{{guide:video_3}}')
        self.assertTrue(render(data,proposal.interpretation(),'guide-only').structural_checks_passed)
        schema = response_schema(data)
        self.assertEqual(schema['$defs']['GuidePart']['properties']['guide_id']['enum'],['video_3'])

    def test_without_a_declared_motion_opening_ordinary_openings_remain_available(self):
        for mode in ['camera','disabled','without_opening']:
            with self.subTest(mode=mode):
                raw = guided_input(); video = raw['videos'][0]
                if mode=='camera':
                    video['role']='camera';video['guidance']['mappings']=[]
                elif mode=='disabled': video['guidance']['enabled']=False
                else: video['guidance']['prompt_en']='Follow the declared trajectory.'
                data = CompileInput.model_validate(raw)
                narrative = ('{{guide:video_3}} ' if mode!='disabled' else '')+'The scene opens with <Subject 5> waiting.'
                self.assertTrue(render(data,plan(narrative,summary='<Subject 5> approaches <Subject 8>.'),'ordinary').structural_checks_passed)

    def test_additional_actions_dialogue_and_unmapped_subject_openings_remain_available(self):
        raw = guided_input()
        raw['active_units'].append(dict(subject=9,name='Observer',role='character',definition_mode='manual',
            description_en='a person wearing a red coat',confirmed=True,sources=[dict(picture_id='person',attribute='identity')]))
        raw['dialogues']=[dict(id='d1',text='  Sono qui! ',language='Italian',speaker_subject=5,confirmed=True)]
        data = CompileInput.model_validate(raw)
        result = render(data,plan('The scene opens with <Subject 9> waiting. {{guide:video_3}} {{dialogue:d1}} <Subject 5> raises a hand.'),'extra')
        self.assertIn('<d>[Italian]   Sono qui! </d>.',result.prompt)
        self.assertIn('<Subject 5> raises a hand.',result.prompt)
        self.assertEqual(result.prompt.count(GUIDE),1)
        lettering='<Subject 5> points at a sign reading "FIRST FRAME".'
        self.assertIn(lettering,render(data,plan('{{guide:video_3}} {{dialogue:d1}} '+lettering),'lettering').prompt)
        question = CurrentInterpretation(narrative_en=None,estimated_duration_s=None,summary_en=None,
            question='Vuoi usare l’apertura della guida o quella della richiesta?')
        self.assertEqual(render(data,question,'question').status,'clarification_needed')


class MotionGuidePersistenceTests(unittest.TestCase):
    setUp = m5.M5ApiTests.setUp
    tearDown = m5.M5ApiTests.tearDown
    view = m5.M5ApiTests.view
    command = m5.M5ApiTests.command
    save = m5.M5ApiTests.save
    compile = m5.M5ApiTests.compile

    def test_new_generation_preserves_exact_older_prompt_and_snapshot(self):
        current=self.client.post(f'/api/cuts/{self.cut}/items',json=self.command(kind='video')).json()
        raw=current['draft_input'];video=raw['videos'][-1]
        video.update(role='camera_and_subject_motion',description_en='the declared guide',duration_s=6.0,
            confirmed=True,linked_to_h3=True,file_exists=True,guidance=dict(enabled=True,
                mappings=[dict(figure='the mannequin',role='motion',subject=1)],
                prompt_en='Opening: the character is outside the frame. At 0.5s the character enters.'))
        self.save(raw)
        legacy_text='  Exact old prompt.\n\nThe scene opens with <Subject 1> walking.\n'
        response=self.client.put(f'/api/cuts/{self.cut}/manual',json=self.command(text=legacy_text))
        self.assertEqual(response.status_code,200,response.text)
        old=copy.deepcopy(response.json()['versions'][-1])
        self.fake.plan=CurrentInterpretation(narrative_en='{{guide:video_1}}',
            summary_en='<Subject 1> enters using <Video 1>.',estimated_duration_s=6.0,question=None)
        new=self.compile()
        retained=next(v for v in self.view()['versions'] if v['id']==old['id'])
        self.assertEqual(retained,old)
        self.assertEqual(self.client.get(f"/api/cuts/{self.cut}/text?version_id={old['id']}").text,legacy_text)
        self.assertEqual(CompileInput.model_validate(new['input_snapshot']).model_dump(),
                         CompileInput.model_validate(old['input_snapshot']).model_dump())
        self.assertNotIn('The scene opens with <Subject 1> walking.',new['text'])
        self.assertIn('motion of <Subject 1> follow the "the mannequin" proxy',new['text'])
        self.assertEqual(self.fake.calls,1)


if __name__=='__main__': unittest.main()
