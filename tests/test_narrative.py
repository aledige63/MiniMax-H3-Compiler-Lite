import json
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.compiler import StructuralError, render
from app.domain import CompileInput, Interpretation
from app.interpreter import OllamaClient
from app.narrative import NarrativePlan, response_schema
from test_m0 import data, structured_plan
from test_shots import preset


class NarrativePlanTests(unittest.TestCase):
    def proposal(self, parts, **extra):
        return NarrativePlan.model_validate(dict(narrative_parts=parts,
            summary_en='<Subject 1> speaks and looks toward the door.',
            estimated_duration_s=8.0, question=None, **extra))

    def test_native_speech_is_inserted_between_actions_with_exact_words_and_concurrent_action(self):
        wire = structured_plan() | dict(summary_en='<Subject 1> speaks as <Subject 2> enters.')
        plan = NarrativePlan.model_validate(wire)
        inputs = data()
        result = render(inputs, plan.interpretation(), 'ordered')
        self.assertTrue(result.structural_checks_passed)
        detailed = result.prompt.split('detailed_description:\n')[1].split('\n\noverall_soundscape:')[0]
        self.assertLess(detailed.index('looks toward the camera'), detailed.index('<d>'))
        self.assertIn('</d>. While <Subject 1> speaks, <Subject 2> enters', detailed)
        self.assertEqual(detailed.count('<d>[Italian] Sono pronta.</d>.'), 1)
        self.assertEqual(wire['narrative_parts'][0]['action_en'], plan.interpretation().narrative_en.split(' {{')[0])

    def test_general_camera_is_a_required_event_and_standard_choices_are_rendered(self):
        inputs = data().model_copy(update={'camera': None})
        raw = inputs.model_dump()
        raw['camera'] = dict(framing='medium_close', angle='eye_level', movement='static', placement='throughout')
        inputs = CompileInput.model_validate(raw)
        parts = [dict(camera_id='main'), dict(action_en='The scene opens with <Subject 1> sitting on the sofa.'),
                 dict(dialogue_id='d1')]
        result = render(inputs, self.proposal(parts).interpretation(), 'fixed-camera')
        detailed = result.prompt.split('detailed_description:\n')[1].split('\n\noverall_soundscape:')[0]
        self.assertIn('Maintain the following camera setup throughout the cut.', detailed)
        self.assertIn('Use a medium close-up.', detailed)
        self.assertIn('Use an eye-level angle.', detailed)
        self.assertEqual(detailed.count('The camera holds a static shot.'), 1)
        self.assertIn('The scene opens with <Subject 1> sitting on the sofa.', detailed)
        for invalid in (parts[1:], [parts[1], parts[0], parts[2]], [parts[0], *parts]):
            with self.subTest(parts=invalid), self.assertRaises(StructuralError):
                render(inputs, self.proposal(invalid).interpretation(), 'missing-camera')
        self.assertIn('CameraPart', response_schema(inputs)['$defs'])

    def test_camera_during_and_after_dialogue_is_bound_to_the_selected_line(self):
        for placement, parts in (
            ('during_dialogue', [dict(action_en='<Subject 1> sits.'), dict(camera_id='main'), dict(dialogue_id='d1')]),
            ('after_dialogue', [dict(action_en='<Subject 1> sits.'), dict(dialogue_id='d1'), dict(camera_id='main')]),
        ):
            raw = data().model_dump()
            raw['camera'] = dict(movement='push_in', speed='slow', placement=placement, dialogue_id='d1')
            inputs = CompileInput.model_validate(raw)
            detailed = render(inputs, self.proposal(parts).interpretation(), 'timed-camera').prompt.split('detailed_description:\n')[1]
            camera_position = detailed.index('The camera pushes in at slow speed.')
            speech_position = detailed.index('<d>[Italian] Sono pronta.</d>.')
            self.assertEqual(camera_position < speech_position, placement == 'during_dialogue')
            swapped = [parts[0], parts[2], parts[1]]
            with self.assertRaisesRegex(StructuralError, 'fase richiesta'):
                render(inputs, self.proposal(swapped).interpretation(), 'wrong-camera-phase')
            interleaved = [parts[0], parts[1], dict(action_en='<Subject 1> looks left.'), parts[2]]
            self.assertTrue(render(inputs, self.proposal(interleaved).interpretation(), 'camera-with-action').structural_checks_passed)

    def test_audio_slot_order_does_not_set_speech_order_or_change_transcript(self):
        raw = data().model_dump()
        raw['dialogues'] = []
        base = dict(media_id='fixture', measured_duration_s=2.0, sample_count=16000, sample_rate=8000,
            channels=1, role='speech', mode='copy', confirmed=True, linked_to_h3=True, speaker_subject=1)
        raw['audio_references'] = [dict(base, id='a8', slot=2, name='Prima', transcript='  Prima!  '),
                                   dict(base, id='a9', slot=1, name='Seconda', transcript='Poi.')]
        parts = [dict(dialogue_id='a8'), dict(action_en='<Subject 1> looks left.'), dict(dialogue_id='a9'),
                 dict(action_en='Then, <Subject 1> smiles.')]
        result = render(CompileInput.model_validate(raw), self.proposal(parts).interpretation(), 'audio-events')
        detailed = result.prompt.split('detailed_description:\n')[1].split('\n\noverall_soundscape:')[0]
        self.assertIn('  Prima!  </d>. <Subject 1> looks left.', detailed)
        self.assertIn('Poi.</d>. Then, <Subject 1> smiles.', detailed)
        self.assertLess(detailed.index('Prima!'), detailed.index('Poi.'))
        self.assertEqual(detailed.count('(S1) says:'), 2)
        self.assertNotIn('After', detailed)

    def test_off_screen_audio_is_carried_from_model_to_the_spoken_line(self):
        raw = data().model_dump()
        raw.update(
            request="<Subject 1> guarda a destra. <Subject 2> non inquadrata dalla telecamera <Audio 1>.",
            dialogues=[],
            audio_references=[dict(
                id="a10", slot=1, media_id="fixture", role="speech", mode="copy",
                measured_duration_s=2.0, sample_rate=8000, sample_count=16000, channels=1,
                speaker_subject=2, transcript="  Eccomi!  ", confirmed=True, linked_to_h3=True,
            )],
        )
        inputs = CompileInput.model_validate(raw)
        wire = dict(
            narrative_parts=[
                dict(action_en="<Subject 1> looks right."),
                dict(off_screen_audio_id="a10", listener_subject=1),
                dict(action_en="<Subject 1> looks back at the camera."),
            ],
            summary_en="<Subject 1> looks right while <Subject 2> speaks off-screen.",
            estimated_duration_s=8.0, question=None,
        )
        client = OllamaClient()
        reply = dict(done=True, done_reason="stop", message=dict(content=json.dumps(wire)))
        with patch.object(client, "_request", side_effect=[dict(models=[dict(name="local", digest="test")]), reply]) as request:
            result = client.compile(inputs, "local")
        self.assertEqual(result.status, "proposal")
        schema = request.call_args.args[1]["format"]
        self.assertEqual(schema["$defs"]["OffScreenAudioPart"]["properties"]["off_screen_audio_id"]["enum"], ["a10"])
        detailed = result.prompt.split("detailed_description:\n")[1].split("\n\noverall_soundscape:")[0]
        self.assertIn("Copy the entire speech recording from <Audio 1> unchanged", detailed)
        listener_cue = "<Subject 1> listens with lips completely closed throughout the off-screen line."
        self.assertEqual(detailed.count(listener_cue), 1)
        self.assertLess(detailed.index(listener_cue), detailed.index("<Subject 2> (S1)"))
        self.assertNotIn("natural lip movements", detailed)
        self.assertIn("<Subject 2> (S1), who remains outside the frame, says in an off-screen voiceover: "
                      "<d>[Italian]   Eccomi!  </d>. <Subject 1> looks back at the camera.", detailed)
        self.assertEqual(detailed.count("</d>."), 1)
        archived = Interpretation.model_validate(result.interpretation.model_dump())
        self.assertEqual(render(inputs, archived, "replayed").prompt, result.prompt)

        wire["narrative_parts"][1]["listener_subject"] = 2
        with self.assertRaisesRegex(StructuralError, "distinto dal parlante"):
            render(inputs, NarrativePlan.model_validate(wire).interpretation(), "same-speaker")
        wire["narrative_parts"][1]["listener_subject"] = 1
        wire["narrative_parts"].append(dict(dialogue_id="a10"))
        duplicate = NarrativePlan.model_validate(wire).interpretation()
        with self.assertRaisesRegex(StructuralError, r"ha ripetuto: Audio 1"):
            render(inputs, duplicate, "duplicate")

    def test_shots_and_guide_keep_their_positions_around_dialogue_and_actions(self):
        raw = data().model_dump()
        raw.update(request='#full su <Subject 1>. A 4 secondi #close su <Subject 1>.',
            shot_presets=[preset('full', 'full').model_dump(), preset('close', 'close').model_dump()],
            pictures=[dict(id='style', slot=9, role='style', description_en='watercolour rendering',
                guidance=dict(enabled=True), confirmed=True, linked_to_h3=True)])
        # La fixture M0 usa le proprie sorgenti numeriche; la guida aggiunta non le sostituisce.
        from test_picture_registry import catalogue_input
        base = catalogue_input()
        raw['active_units'] = base['active_units']
        raw['pictures'] = base['pictures'] + raw['pictures']
        parts = [dict(shot_id='s1'), dict(guide_id='picture_9'), dict(action_en='<Subject 1> looks left.'),
                 dict(dialogue_id='d1'), dict(shot_id='s2'), dict(action_en='<Subject 1> smiles.')]
        result = render(CompileInput.model_validate(raw), self.proposal(parts).interpretation(), 'camera-events')
        self.assertTrue(result.structural_checks_passed)
        detailed = result.prompt.split('detailed_description:\n')[1].split('\n\noverall_soundscape:')[0]
        self.assertLess(detailed.index('[Shot 1]'), detailed.index('Use <Picture 9> as the visual-style guide.'))
        self.assertLess(detailed.index('</d>.'), detailed.index('[Shot 2] At 00:04.000'))
        self.assertNotIn('{{', detailed)

    def test_clarification_has_no_partial_actions_summary_or_soundscape(self):
        raw = dict(narrative_parts=None, summary_en=None, soundscape_en=None, estimated_duration_s=None, question='Quale camera?')
        self.assertEqual(NarrativePlan(**raw).interpretation().question, 'Quale camera?')
        for change in [dict(narrative_parts=[dict(dialogue_id='d1')]), dict(summary_en='Someone speaks.'), dict(soundscape_en='Wind.')]:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                NarrativePlan(**(raw | change))

    def test_mixed_part_shapes_and_empty_proposals_are_rejected(self):
        for parts in [[], [dict(action_en='Walks.', dialogue_id='d1')], [dict(unknown='d1')]]:
            with self.subTest(parts=parts), self.assertRaises(ValidationError):
                self.proposal(parts)

    def test_invalid_inline_markers_are_rejected_without_splitting_or_repairing_action(self):
        for action in ['<Subject 1> says {{dialogue:d1}}', '   ']:
            plan = self.proposal([dict(action_en=action)])
            with self.subTest(action=action), self.assertRaises(StructuralError):
                plan.interpretation()
        plan = self.proposal([dict(action_en='<Subject 1> turns and says'), dict(dialogue_id='d1')])
        with self.assertRaises(StructuralError):
            render(data(), plan.interpretation(), 'no-punctuation-repair')

    def test_client_uses_new_schema_in_one_inference_and_historical_plan_stays_readable(self):
        wire = structured_plan() | dict(summary_en='<Subject 1> speaks as <Subject 2> enters.')
        client = OllamaClient()
        reply = dict(done=True, done_reason='stop', message=dict(content=json.dumps(wire)))
        with patch.object(client, '_request', side_effect=[dict(models=[dict(name='local', digest='test')]), reply]) as request:
            result = client.compile(data(), 'local')
        self.assertEqual(result.status, 'proposal')
        self.assertEqual(result.metrics.inference_calls, 1)
        self.assertEqual(request.call_count, 2)
        schema = request.call_args.args[1]['format']
        self.assertIn('narrative_parts', schema['anyOf'][0]['required'])
        self.assertNotIn('narrative_en', schema['anyOf'][0]['properties'])
        self.assertEqual(schema['$defs']['DialoguePart']['properties']['dialogue_id']['enum'], ['d1'])
        self.assertNotIn('Sono pronta.', json.dumps(request.call_args.args[1]))
        archived = result.interpretation.model_dump()
        self.assertEqual(Interpretation.model_validate(archived).narrative_en, archived['narrative_en'])

    def test_decoder_does_not_offer_unavailable_speech_shots_or_guides(self):
        schema = response_schema(CompileInput(request='Una stanza vuota.'))
        array = schema['anyOf'][0]['properties']['narrative_parts']
        self.assertEqual(array['items']['anyOf'], [{'$ref': '#/$defs/ActionPart'}])

    def test_decoder_requires_custom_soundscape_for_proposal_but_allows_null_for_question(self):
        raw = data().model_dump() | dict(ambient_sound=False, soundscape_text='Bussano alla porta.')
        schema = response_schema(CompileInput.model_validate(raw))
        proposal, question = schema['anyOf']
        self.assertEqual(proposal['properties']['soundscape_en']['type'], 'string')
        self.assertIn('soundscape_en', proposal['required'])
        self.assertEqual(question['properties']['soundscape_en']['type'], 'null')
        self.assertEqual(question['properties']['question']['type'], 'string')
        self.assertEqual(response_schema(data())['anyOf'][0]['properties']['soundscape_en']['type'], 'null')
