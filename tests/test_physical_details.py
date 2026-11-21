import copy
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from pydantic import ValidationError

from app.compiler import SECTIONS, StructuralError, render
from app.domain import CompileInput, CurrentInterpretation, Interpretation
from app.exporting import reference_notes
from app.interpreter import OllamaClient, input_hash, model_context
from app.narrative import NarrativePlan, response_schema
from app.validation import completion_issues
from test_picture_registry import catalogue_input
import test_definition_preferences as definitions


def detail(**changes):
    return dict(id='p1', description='un uncino di ferro con attacco in cuoio',
                body_location='mano destra', operation='replace', picture_id='hook', **changes)


TRANSLATION = dict(description_en='an iron hook with a leather cuff', body_location_en='right hand')


def physical_input():
    raw = catalogue_input()
    raw['pictures'].append(dict(id='hook', slot=3, name='Uncino', role='object',
        description_en='an iron hook with a leather cuff', confirmed=True, linked_to_h3=True))
    raw['active_units'][0]['physical_details'] = [detail()]
    raw['declared_duration_s'] = 5.0
    return raw


def plan(translations=None):
    return CurrentInterpretation(narrative_en='<Subject 1> raises the right forearm.',
        summary_en='<Subject 1> raises the arm bearing the hook.',
        physical_details_en={'s1_p1': TRANSLATION} if translations is None else translations,
        estimated_duration_s=5.0, question=None)


class PhysicalDetailTests(unittest.TestCase):
    def test_replacement_has_one_subject_and_explicit_partial_retention(self):
        data = CompileInput.model_validate(physical_input())
        prompt = render(data, plan(), 'hook').prompt
        sections = dict(block.split(':\n', 1) for block in prompt.split('\n\n'))
        self.assertEqual(tuple(sections), SECTIONS)
        phrase = 'the right hand is replaced by an iron hook with a leather cuff from <Picture 3>'
        self.assertIn(phrase, sections['subject_definitions'])
        self.assertIn('physical details take precedence over the source appearance', sections['subject_definitions'])
        self.assertIn(phrase, sections['retention_analysis'])
        self.assertIn('partially_preserved', sections['retention_analysis'])
        self.assertNotIn('fully_preserved', sections['retention_analysis'])
        self.assertNotIn('<Subject 2>', prompt)
        self.assertNotIn('<Picture 3> (', sections['retention_analysis'])
        self.assertEqual(sections['detailed_description'], '[Shot 1] <Subject 1> raises the right forearm.')
        self.assertNotIn('left hand', prompt)

    def test_add_modify_and_description_only_are_distinct_and_slots_follow_ids(self):
        raw = physical_input()
        raw['pictures'][-1]['slot'] = 8
        raw['active_units'][0]['physical_details'] += [
            dict(id='p2', description='una cicatrice', body_location='guancia sinistra', operation='add'),
            dict(id='p3', description='iride verde', body_location='occhio sinistro', operation='modify')]
        translations = {'s1_p1': TRANSLATION,
            's1_p2': dict(description_en='a scar', body_location_en='left cheek'),
            's1_p3': dict(description_en='a green iris', body_location_en='left eye')}
        prompt = render(CompileInput.model_validate(raw), plan(translations), 'multiple').prompt
        self.assertIn('from <Picture 8>', prompt)
        self.assertNotIn('<Picture 3>', prompt)
        self.assertIn('a scar is added at the left cheek', prompt)
        self.assertIn('the left eye is modified as follows: a green iris', prompt)

    def test_details_belong_to_the_selected_subject_even_with_the_same_local_id(self):
        raw = physical_input()
        second = copy.deepcopy(raw['active_units'][0])
        second.update(subject=2, name='Beth', definition_mode='manual', description_en='the second woman')
        second['physical_details'] = [dict(id='p1', description='una cicatrice', body_location='guancia sinistra', operation='add')]
        raw['active_units'].append(second)
        translations = {'s1_p1': TRANSLATION, 's2_p1': dict(description_en='a scar', body_location_en='left cheek')}
        prompt = render(CompileInput.model_validate(raw), plan(translations), 'two-subjects').prompt
        definitions_text = prompt.split('\n\nsummary:')[0].splitlines()[1:]
        self.assertIn('right hand', definitions_text[0]); self.assertNotIn('scar', definitions_text[0])
        self.assertIn('left cheek', definitions_text[1]); self.assertNotIn('hook', definitions_text[1])

    def test_context_and_schema_include_only_active_detail_sources_and_exact_translation_keys(self):
        raw = physical_input()
        raw['pictures'].append(dict(id='unused', slot=9, description_en='UNUSED'))
        data = CompileInput.model_validate(raw)
        context = model_context(data)
        self.assertEqual(context['physical_details']['s1_p1']['subject'], '<Subject 1>')
        self.assertEqual(context['physical_details']['s1_p1']['picture'], '<Picture 3>')
        self.assertEqual(context['physical_details']['s1_p1']['body_location'], 'mano destra')
        self.assertNotIn('UNUSED', json.dumps(context))
        schema = response_schema(data)
        translated = schema['anyOf'][0]['properties']['physical_details_en']
        self.assertEqual(translated['required'], ['s1_p1'])
        self.assertFalse(translated['additionalProperties'])
        self.assertEqual(schema['anyOf'][1]['properties']['physical_details_en'], {'type': 'null'})

    def test_missing_unexpected_and_unsafe_translations_do_not_get_repaired(self):
        data = CompileInput.model_validate(physical_input())
        for translations in ({}, {'s2_p1': TRANSLATION}, {'s1_p1': dict(TRANSLATION, description_en='<Subject 9>')},
                             {'s1_p1': dict(TRANSLATION, body_location_en='   ')},
                             {'s1_p1': dict(TRANSLATION, description_en='retention_analysis: test')}):
            with self.subTest(translations=translations), self.assertRaises(StructuralError):
                render(data, plan(translations), 'bad-translation')
        empty = CompileInput.model_validate(catalogue_input())
        with self.assertRaises(StructuralError):
            render(empty, plan(), 'unexpected-translation')

    def test_one_model_call_translates_and_archives_the_detail(self):
        data = CompileInput.model_validate(physical_input())
        wire = dict(narrative_parts=[dict(action_en='<Subject 1> raises the right forearm.')],
            summary_en='<Subject 1> raises the arm bearing the hook.', physical_details_en={'s1_p1': TRANSLATION},
            estimated_duration_s=5.0, question=None)
        client = OllamaClient()
        response = dict(done=True, done_reason='stop', message=dict(content=json.dumps(wire)))
        with patch.object(client, '_request', side_effect=[dict(models=[dict(name='test', digest='fixture')]), response]):
            result = client.compile(data, 'test')
        self.assertEqual(result.status, 'proposal'); self.assertEqual(result.metrics.inference_calls, 1)
        archived = Interpretation.model_validate_json(result.interpretation.model_dump_json())
        self.assertEqual(render(data, archived, 'replay').prompt, result.prompt)
        wire['physical_details_en'] = None
        response['message']['content'] = json.dumps(wire)
        with patch.object(client, '_request', side_effect=[dict(models=[dict(name='test', digest='fixture')]), response]):
            result = client.compile(data, 'test')
        self.assertEqual(result.error_code, 'invalid_structure'); self.assertEqual(result.metrics.inference_calls, 1)

    def test_detail_pictures_require_description_confirmation_link_and_compatible_role(self):
        for field, value in [('description_en', ''), ('confirmed', False), ('linked_to_h3', False), ('role', 'style')]:
            raw = physical_input(); raw['pictures'][-1][field] = value
            with self.subTest(field=field), self.assertRaises(ValidationError):
                CompileInput.model_validate(raw)

    def test_missing_picture_duplicate_ids_non_character_and_reserved_text_are_rejected(self):
        for change in ('missing-picture', 'duplicate-id', 'role', 'tag', 'whitespace', 'context'):
            raw = physical_input(); unit = raw['active_units'][0]
            if change == 'missing-picture': raw['pictures'].pop()
            elif change == 'duplicate-id': unit['physical_details'].append(detail())
            elif change == 'role': unit['role'] = 'object'
            elif change == 'tag': unit['physical_details'][0]['description'] = '<Picture 8>'
            elif change == 'whitespace': unit['physical_details'][0]['body_location'] = '  '
            else: unit['physical_details'][0].update(origin='context', picture_id=None)
            with self.subTest(change=change), self.assertRaises(ValidationError):
                CompileInput.model_validate(raw)

    def test_incomplete_fields_have_visible_labels_and_picture_confirmations(self):
        raw = physical_input(); raw['active_units'][0]['physical_details'][0]['description'] = ''
        raw['pictures'][-1]['linked_to_h3'] = False
        issues = completion_issues(raw)
        self.assertTrue(any('dettaglio fisico 1' in issue and 'Descrizione del dettaglio' in issue for issue in issues))
        self.assertTrue(any('Picture 3' in issue and 'H3' in issue for issue in issues))

    def test_retained_context_details_are_not_declared_as_new_alterations(self):
        raw = physical_input()
        unit = raw['active_units'][0]
        unit['sources'] = [dict(origin='context', attribute='identity')]
        unit['physical_details'][0].update(origin='context', picture_id=None)
        raw['pictures'] = []
        raw['continuity'] = dict(mode='latent', declared_state='<Subject 1> è in piedi.')
        data = CompileInput.model_validate(raw)
        prompt = render(data, plan(), 'context').prompt
        self.assertIn('fully_preserved', prompt); self.assertNotIn('partially_preserved', prompt)
        self.assertNotIn('<Picture', prompt)
        self.assertEqual(data.active_pictures, [])

    def test_empty_defaults_preserve_old_input_hash_and_prompt(self):
        raw = catalogue_input(); before = CompileInput.model_validate(raw)
        raw['active_units'][0]['physical_details'] = []
        after = CompileInput.model_validate(raw)
        self.assertEqual(input_hash(before), input_hash(after))
        self.assertNotIn('physical_details', after.model_dump()['active_units'][0])
        self.assertNotIn('physical_details', model_context(after))
        self.assertEqual(response_schema(after)['anyOf'][0]['properties']['physical_details_en'], {'type': 'null'})
        self.assertEqual(render(before, definitions.PLAN, 'old').prompt, render(after, definitions.PLAN, 'new').prompt)

    def test_question_cannot_contain_a_translated_detail(self):
        with self.assertRaises(ValidationError):
            NarrativePlan(narrative_parts=None, summary_en=None, physical_details_en={'s1_p1': TRANSLATION},
                estimated_duration_s=None, question='Quale mano?')


class PhysicalDetailApiTests(unittest.TestCase):
    setUp = definitions.DefinitionApiTests.setUp
    tearDown = definitions.DefinitionApiTests.tearDown
    view = definitions.DefinitionApiTests.view
    command = definitions.DefinitionApiTests.command
    save = definitions.DefinitionApiTests.save
    compile = definitions.DefinitionApiTests.compile

    def add_detail(self):
        response = self.client.post(f'/api/cuts/{self.cut}/items', json=self.command(kind='picture'))
        self.assertEqual(response.status_code, 200, response.text)
        raw = response.json()['draft_input']; picture = raw['pictures'][-1]
        picture.update(name='Uncino', role='object', description_en='an iron hook', confirmed=True, linked_to_h3=True)
        raw['active_units'][0]['physical_details'] = [detail() | {'picture_id': picture['id']}]
        self.save(raw); self.fake.plan = plan()
        return picture['id']

    def new_cut(self, *, new_scene=False, inherit=False):
        project = self.client.get('/api/projects').json()[0]
        if new_scene:
            response = self.client.post(f"/api/projects/{project['id']}/scenes", json=dict(command_id=str(uuid4()), expected_revision=project['revision'], name='Altra'))
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()['cuts'][0]['id']
        scene = project['scenes'][0]
        response = self.client.post(f"/api/scenes/{scene['id']}/cuts", json=dict(command_id=str(uuid4()), expected_revision=scene['revision'], name='Segue', inherit_references=inherit))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()['id']

    def test_save_reload_and_inheritance_keep_details_and_require_new_picture_links(self):
        picture_id = self.add_detail()
        expected = self.view()['draft_input']['active_units'][0]['physical_details']
        self.assertEqual(self.fake.calls, 0)
        self.assertEqual(next(t for t in self.view()['tokens'] if t['id'] == picture_id)['association'], 'bound')
        new_cut = self.new_cut(inherit=True)
        inherited = self.client.get(f'/api/cuts/{new_cut}').json()['draft_input']
        self.assertEqual(inherited['active_units'][0]['physical_details'], expected)
        self.assertTrue(all(not p['linked_to_h3'] for p in inherited['pictures']))
        self.assertEqual(self.fake.calls, 0)

    def test_library_reuse_includes_detail_picture_and_resolves_new_slot_without_new_subject(self):
        picture_id = self.add_detail(); view = self.view()
        unit_id = view['unit_ids']['1']; original_pictures = view['draft_input']['pictures']
        self.cut = self.new_cut(new_scene=True)
        slots = {p['id']: slot for p, slot in zip(original_pictures, [6, 8])}
        response = self.client.post(f'/api/cuts/{self.cut}/reuse', json=self.command(kind='unit', reference_id=unit_id, slots=slots))
        self.assertEqual(response.status_code, 200, response.text)
        raw = response.json()['draft_input']
        self.assertEqual(len(raw['active_units']), 1)
        self.assertEqual({p['id'] for p in raw['pictures']}, set(slots))
        self.assertEqual(raw['active_units'][0]['physical_details'][0]['picture_id'], picture_id)
        raw['request'] = '<Subject 1> alza il braccio.'
        for picture in raw['pictures']: picture['linked_to_h3'] = True
        prompt = render(CompileInput.model_validate(raw), plan(), 'reused').prompt
        self.assertIn('hook with a leather cuff from <Picture 8>', prompt)
        self.assertEqual(self.fake.calls, 0)

    def test_versions_export_and_selected_context_preserve_their_own_detail(self):
        old = self.compile(); picture_id = self.add_detail(); first = self.compile()
        self.assertNotIn('physical details take precedence', old['text'])
        self.assertIn('partially_preserved', first['text'])
        self.assertTrue(any('Sostituzione' in note and 'mano destra' in note and 'Picture 2' in note for note in reference_notes(first)))
        raw = self.view()['draft_input']; raw['active_units'][0]['physical_details'][0]['description'] = 'un uncino di bronzo'
        self.save(raw)
        previous_cut = self.cut; self.cut = self.new_cut()
        raw = self.view()['draft_input']; raw['continuity'] = dict(mode='latent', declared_state='<Subject 1> è in piedi.', previous_cut_id=previous_cut, previous_version_id=first['id'])
        self.save(raw)
        response = self.client.post(f'/api/cuts/{self.cut}/context-subject', json=self.command(subject=1))
        self.assertEqual(response.status_code, 200, response.text)
        raw = response.json()['draft_input']; unit = raw['active_units'][0]
        self.assertEqual(unit['physical_details'][0]['description'], detail()['description'])
        self.assertEqual(unit['physical_details'][0]['origin'], 'context')
        self.assertIsNone(unit['physical_details'][0]['picture_id'])
        unit['confirmed'] = True; raw['request'] = '<Subject 1> alza il braccio.'
        self.save(raw)
        library = self.client.get(f"/api/projects/{self.view()['project_id']}/library").json()
        canonical = library['units'][0]['physical_details'][0]
        self.assertEqual(canonical['description'], 'un uncino di bronzo')
        self.assertEqual(canonical['picture_id'], picture_id)
        self.assertEqual(self.client.get(f'/api/cuts/{previous_cut}/text?version_id={first["id"]}').text, first['text'])
        self.assertEqual(self.client.get(f'/api/cuts/{previous_cut}/text?version_id={old["id"]}').text, old['text'])
        self.assertIn('fully_preserved', render(CompileInput.model_validate(raw), plan(), 'context').prompt)

        # Cambiare esplicitamente la Picture di un dettaglio nel cut di contesto
        # aggiorna l'associazione canonica, senza ripristinare la vecchia immagine.
        response = self.client.post(f'/api/cuts/{self.cut}/items', json=self.command(kind='picture'))
        raw = response.json()['draft_input']; new_picture = raw['pictures'][-1]
        new_picture.update(name='Altro uncino', role='object', description_en='a bronze hook', confirmed=True, linked_to_h3=True)
        raw['active_units'][0]['physical_details'][0].update(origin='picture', picture_id=new_picture['id'])
        self.save(raw)
        library = self.client.get(f"/api/projects/{self.view()['project_id']}/library").json()
        self.assertEqual(library['units'][0]['physical_details'][0]['picture_id'], new_picture['id'])

    def test_manual_based_on_old_physical_details_requires_explicit_reconciliation(self):
        self.add_detail(); generated = self.compile()
        raw = self.view()['draft_input']
        raw['active_units'][0]['physical_details'][0]['body_location'] = 'mano sinistra'
        self.save(raw)
        response = self.client.put(f'/api/cuts/{self.cut}/manual', json=self.command(text=generated['text'], base_candidate_id=generated['id']))
        self.assertEqual(response.status_code, 200, response.text)
        version = response.json()['versions'][-1]
        command = self.command(version_id=version['id'])
        blocked = self.client.post(f'/api/cuts/{self.cut}/confirm', json=command)
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertEqual(blocked.json()['detail']['code'], 'reference_reconciliation_required')
        command['acknowledge_reference_changes'] = True
        confirmed = self.client.post(f'/api/cuts/{self.cut}/confirm', json=command)
        self.assertEqual(confirmed.status_code, 200, confirmed.text)

    def test_stale_cut_cannot_overwrite_a_newer_detail_in_the_library(self):
        self.add_detail(); original = self.cut
        self.cut = self.new_cut(inherit=True)
        stale = self.view()['draft_input']
        self.cut = original
        fresh = self.view()['draft_input']; fresh['active_units'][0]['physical_details'][0]['description'] = 'un uncino di bronzo'
        self.save(fresh)
        self.cut = self.client.get('/api/projects').json()[0]['scenes'][0]['cuts'][-1]['id']
        stale['active_units'][0]['physical_details'][0]['description'] = 'un uncino di argento'
        response = self.client.put(f'/api/cuts/{self.cut}/draft', json=self.command(input=stale))
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(response.json()['detail']['code'], 'reference_conflict')

    def test_incomplete_draft_is_saved_but_compile_does_not_start_an_inference(self):
        self.add_detail(); raw = self.view()['draft_input']
        raw['active_units'][0]['physical_details'][0]['body_location'] = ''
        saved = self.save(raw)
        self.assertTrue(any('Posizione sul corpo' in issue for issue in saved['catalogue_issues']))
        response = self.client.post(f'/api/cuts/{self.cut}/compile', json=self.command(cut_id=self.cut, input=raw, model='local-test'))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()['detail']['code'], 'incomplete_input')
        self.assertEqual(self.fake.calls, 0)

    def test_unregistered_detail_picture_is_rejected_without_changing_the_draft(self):
        self.add_detail(); before = self.view()['draft_input']; raw = copy.deepcopy(before)
        raw['active_units'][0]['physical_details'][0]['picture_id'] = str(uuid4())
        response = self.client.put(f'/api/cuts/{self.cut}/draft', json=self.command(input=raw))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.view()['draft_input'], before)
