import copy
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from pydantic import ValidationError

from app.compiler import SECTIONS, StructuralError, render
from app.domain import CompileInput, CurrentInterpretation
from app.exporting import reference_notes
from app.interpreter import OllamaClient, input_hash, model_context
from app.narrative import NarrativePlan, response_schema
from app.physical import unit_picture_ids
from app.subjects import remap_subjects, draft_subject_numbers
from test_picture_registry import catalogue_input
import test_definition_preferences as definitions
import test_physical_details as physical


TRANSLATION = dict(measurements_en='20 cm tall, 6.5 cm in diameter', comparison_en='fits comfortably in one hand')


def scale(**changes):
    return dict(measurements='alta 20 cm, diametro 6,5 cm', comparison='si impugna comodamente con una mano', **changes)


def bottle_input():
    raw = catalogue_input()
    raw['pictures'] = [raw['pictures'][0] | dict(role='object', description_en='a small blue bottle held in a hand')]
    raw['active_units'] = [dict(subject=1, name='Bottiglietta', role='object', definition_mode='manual',
        description_en='the small blue bottle', confirmed=True, sources=[dict(attribute='object', picture_id='face')],
        scale=scale(picture_id='face'))]
    raw.update(request='<Subject 1> rimane sul tavolo.', declared_duration_s=5.0)
    return raw


def plan(key='s1', translation=None):
    return CurrentInterpretation(narrative_en='<Subject 1> remains on the table.',
        summary_en='<Subject 1> remains on the table.', estimated_duration_s=5.0, question=None,
        scales_en={key: TRANSLATION if translation is None else translation})


class SubjectScaleTests(unittest.TestCase):
    def dedicated_input(self):
        raw=bottle_input()
        raw['pictures'].append(dict(id='dimensional',slot=4,name='Scala in mano',role='scale_reference',
            description_en='the bottle fits in one hand',confirmed=True,linked_to_h3=True))
        raw['active_units'][0]['scale']['picture_id']='dimensional'
        return raw

    def test_dedicated_role_is_active_only_through_scale_and_does_not_create_a_frame_anchor(self):
        raw=self.dedicated_input();data=CompileInput.model_validate(raw)
        self.assertEqual([p.id for p in data.active_pictures],['face','dimensional'])
        self.assertEqual(data.active_picture_guides,[])
        self.assertEqual(model_context(data)['pictures'][1]['role'],'scale_reference')
        prompt=render(data,plan(),'dedicated').prompt
        self.assertIn('as shown in <Picture 4>',prompt)
        self.assertNotIn('frame anchor',prompt)
        self.assertNotIn('<Subject 2>',prompt)
        raw['active_units'][0]['scale']=dict(measurements='alta 20 cm, diametro 6,5 cm',comparison='si impugna comodamente con una mano')
        raw['pictures'][1]['confirmed']=False
        self.assertEqual([p.id for p in CompileInput.model_validate(raw).active_pictures],['face'])

    def test_dedicated_role_cannot_define_appearance_or_a_physical_detail(self):
        for kind in ['source','detail']:
            raw=self.dedicated_input()
            if kind=='source':raw['active_units'][0]['sources'][0]['picture_id']='dimensional'
            else:
                raw['active_units'][0].update(role='character',sources=[dict(attribute='identity',picture_id='face')],
                    physical_details=[dict(id='p1',operation='add',description='una cicatrice',body_location='mano',picture_id='dimensional')])
            with self.subTest(kind=kind),self.assertRaisesRegex(ValidationError,'Dimensioni e scala'):CompileInput.model_validate(raw)

    def test_dedicated_role_requires_picture_confirmations_and_respects_exclusion(self):
        for patch in [dict(confirmed=False),dict(linked_to_h3=False),dict(excluded=True),dict(guidance=dict(enabled=True))]:
            raw=self.dedicated_input();raw['pictures'][1].update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValidationError):CompileInput.model_validate(raw)

    def test_same_photo_defines_object_and_scale_without_an_extra_person_or_picture_entry(self):
        data = CompileInput.model_validate(bottle_input())
        self.assertEqual(len(data.active_pictures), 1)
        self.assertEqual(unit_picture_ids(data.active_units[0].model_dump()), ['face'])
        result = render(data, plan(), 'same-photo')
        sections = dict(block.split(':\n', 1) for block in result.prompt.split('\n\n'))
        self.assertEqual(tuple(sections), SECTIONS)
        for key in ['subject_definitions', 'retention_analysis']:
            self.assertIn('20 cm tall, 6.5 cm in diameter', sections[key])
            self.assertIn('scale as shown in <Picture 1>: fits comfortably in one hand', sections[key])
        self.assertIn('throughout the cut', sections['retention_analysis'])
        self.assertIn('distance and perspective', sections['retention_analysis'])
        self.assertNotIn('<Subject 2>', result.prompt)
        self.assertEqual(sections['retention_analysis'].count('fully_preserved'), 1)
        self.assertNotIn('<Picture 1> (', sections['retention_analysis'])
        self.assertEqual(sections['detailed_description'], '[Shot 1] <Subject 1> remains on the table.')

    def test_second_photo_only_for_scale_is_active_and_uses_current_slot(self):
        raw = bottle_input()
        raw['pictures'].append(dict(id='scale-photo', slot=8, role='object', name='Scala',
            description_en='a hand holding the bottle', confirmed=True, linked_to_h3=True))
        raw['active_units'][0]['scale']['picture_id'] = 'scale-photo'
        data = CompileInput.model_validate(raw)
        self.assertEqual([p.id for p in data.active_pictures], ['face', 'scale-photo'])
        self.assertIn('as shown in <Picture 8>', render(data, plan(), 'slot').prompt)
        self.assertEqual(model_context(data)['scales']['s1']['picture'], '<Picture 8>')
        for change in [dict(confirmed=False), dict(linked_to_h3=False), dict(excluded=True)]:
            invalid = copy.deepcopy(raw); invalid['pictures'][-1].update(change)
            with self.subTest(change=change), self.assertRaises(ValidationError):CompileInput.model_validate(invalid)

    def test_measurement_only_and_picture_comparison_only_do_not_invent_missing_values(self):
        for value, translated in [
            (dict(measurements='altezza 20 cm'), dict(measurements_en='20 cm tall', comparison_en='')),
            (dict(comparison='larga quanto il palmo', picture_id='face'), dict(measurements_en='', comparison_en='as wide as the palm')),
        ]:
            raw = bottle_input(); raw['active_units'][0]['scale'] = value
            result = render(CompileInput.model_validate(raw), plan(translation=translated), 'optional')
            self.assertEqual(result.status, 'proposal')
            if not value.get('measurements'):self.assertNotIn('20 cm', result.prompt)

    def test_comparison_target_is_explicit_and_cannot_be_self_missing_or_excluded(self):
        raw = bottle_input(); other = copy.deepcopy(raw['active_units'][0])
        other.update(subject=4, name='Altro', scale=None)
        raw['active_units'].append(other)
        raw['active_units'][0]['scale'].update(reference_subject_id='stable-other', reference_subject=4)
        data = CompileInput.model_validate(raw)
        self.assertIn('scale relative to <Subject 4> as shown in <Picture 1>', render(data, plan(), 'relative').prompt)
        for target in [1, 3, None]:
            invalid=copy.deepcopy(raw); invalid['active_units'][0]['scale']['reference_subject']=target
            with self.subTest(target=target), self.assertRaises(ValidationError):CompileInput.model_validate(invalid)
        raw['active_units'][1]['excluded']=True
        with self.assertRaises(ValidationError):CompileInput.model_validate(raw)

    def test_empty_and_unsafe_input_is_rejected_but_excluded_unfinished_scale_is_preserved(self):
        for value in [{}, dict(measurements='   '), dict(measurements='<Subject 9>'), dict(comparison='a\nb'), dict(measurements='20 cm', picture_id='face')]:
            raw=bottle_input(); raw['active_units'][0]['scale']=value
            with self.subTest(value=value), self.assertRaises(ValidationError):CompileInput.model_validate(raw)
            raw['active_units'][0]['excluded']=True; raw['request']='Un tavolo vuoto.'
            data=CompileInput.model_validate(raw)
            self.assertNotIn('scales',model_context(data))
            self.assertEqual(data.model_dump()['active_units'][0]['scale'],value)

    def test_missing_added_unsafe_or_changed_measurements_cannot_silently_enter_prompt(self):
        data=CompileInput.model_validate(bottle_input())
        for translations in [None, {}, {'s4':TRANSLATION}, {'s1':dict(TRANSLATION,measurements_en='200 cm tall, 6.5 cm in diameter')},
                             {'s1':dict(TRANSLATION,comparison_en='<Subject 99>')}, {'s1':dict(TRANSLATION,comparison_en='')},
                             {'s1':dict(TRANSLATION,comparison_en='summary: new section')}]:
            proposal=CurrentInterpretation.model_validate(plan().model_dump() | {'scales_en':translations})
            with self.subTest(translations=translations), self.assertRaises(StructuralError):render(data,proposal,'bad')

    def test_exact_schema_keys_and_single_inference_translate_scale(self):
        data=CompileInput.model_validate(bottle_input()); schema=response_schema(data)
        self.assertEqual(schema['anyOf'][0]['properties']['scales_en']['required'],['s1'])
        self.assertFalse(schema['anyOf'][0]['properties']['scales_en']['additionalProperties'])
        self.assertEqual(schema['anyOf'][1]['properties']['scales_en'],dict(type='null'))
        wire=dict(narrative_parts=[dict(action_en='<Subject 1> remains on the table.')],
            summary_en='<Subject 1> remains on the table.',estimated_duration_s=5.0,question=None,scales_en={'s1':TRANSLATION})
        client=OllamaClient()
        response=dict(done=True,done_reason='stop',message=dict(content=json.dumps(wire)))
        with patch.object(client,'_request',side_effect=[dict(models=[dict(name='test',digest='fixture')]),response]) as request:
            result=client.compile(data,'test')
        self.assertEqual(result.status,'proposal',result.issues)
        self.assertEqual(request.call_count,2)  # elenco modelli e una sola inferenza
        self.assertEqual(result.interpretation.scales_en['s1'].measurements_en,TRANSLATION['measurements_en'])

    def test_defaults_keep_legacy_hashes_and_questions_cannot_contain_scale_proposals(self):
        raw=catalogue_input(); before=CompileInput.model_validate(raw)
        raw['active_units'][0]['scale']=None
        after=CompileInput.model_validate(raw)
        self.assertEqual(input_hash(before),input_hash(after))
        self.assertNotIn('scale',after.model_dump()['active_units'][0])
        self.assertNotIn('scales',model_context(after))
        self.assertEqual(response_schema(after)['anyOf'][0]['properties']['scales_en'],dict(type='null'))
        with self.assertRaises(ValidationError):NarrativePlan(narrative_parts=None,summary_en=None,estimated_duration_s=None,question='Quale scala?',scales_en={'s1':TRANSLATION})

    def test_scene_renumbering_remaps_comparison_but_preserves_identity_and_measures(self):
        raw=bottle_input(); raw['active_units'][0]['scale'].update(reference_subject_id='uuid-person',reference_subject=7)
        self.assertIn(7,draft_subject_numbers(raw))
        remapped=remap_subjects(raw,{1:2,7:1})
        self.assertEqual(remapped['active_units'][0]['scale'],raw['active_units'][0]['scale'] | {'reference_subject':1})
        self.assertEqual(raw['active_units'][0]['subject'],1)


class SubjectScaleApiTests(unittest.TestCase):
    setUp=definitions.DefinitionApiTests.setUp
    tearDown=definitions.DefinitionApiTests.tearDown
    view=definitions.DefinitionApiTests.view
    command=definitions.DefinitionApiTests.command
    save=definitions.DefinitionApiTests.save
    compile=definitions.DefinitionApiTests.compile
    new_cut=physical.PhysicalDetailApiTests.new_cut

    def add_bottle(self, *, reference=True, second_photo=False):
        response=self.client.post(f'/api/cuts/{self.cut}/items',json=self.command(kind='unit'))
        self.assertEqual(response.status_code,200,response.text)
        if second_photo:
            response=self.client.post(f'/api/cuts/{self.cut}/items',json=self.command(kind='picture'))
            self.assertEqual(response.status_code,200,response.text)
        raw=response.json()['draft_input']; unit=raw['active_units'][-1]; picture=raw['pictures'][0]
        dimensional=raw['pictures'][-1]
        if second_photo:dimensional.update(name='Scala bottiglia',role='object',description_en='a hand gripping a bottle',confirmed=True,linked_to_h3=True)
        value=scale(picture_id=dimensional['id'])
        if reference:value.update(reference_subject_id=self.view()['unit_ids']['1'],reference_subject=1)
        unit.update(name='Bottiglietta',role='object',definition_mode='manual',description_en='a small blue bottle',
            confirmed=True,sources=[dict(attribute='object',picture_id=picture['id'])],scale=value)
        self.save(raw); self.fake.plan=plan(f's{unit["subject"]}')
        return unit['subject'],dimensional['id']

    def test_save_library_snapshot_and_export_keep_scale_with_one_shared_photo(self):
        number,picture=self.add_bottle(); before=self.view()
        self.assertEqual(len(before['draft_input']['pictures']),1)
        self.assertEqual(self.fake.calls,0)
        version=self.compile()
        self.assertEqual(self.fake.calls,1)
        self.assertEqual(version['input_snapshot']['active_units'][-1]['scale'],before['draft_input']['active_units'][-1]['scale'])
        self.assertIn('20 cm tall',version['text'])
        self.assertTrue(any('Dimensioni e scala' in note and 'Subject 1' in note for note in reference_notes(version)))
        library=self.client.get(f'/api/projects/{before["project_id"]}/library').json()
        canonical=next(u for u in library['units'] if u['name']=='Bottiglietta')['scale']
        self.assertNotIn('reference_subject',canonical)
        self.assertEqual(canonical['reference_subject_id'],before['unit_ids']['1'])
        raw=self.view()['draft_input']; raw['active_units'][-1]['scale']['measurements']='alta 25 cm'
        self.save(raw)
        self.assertEqual(self.view()['versions'][-1],version)

    def test_reuse_other_scene_keeps_uuid_and_waits_for_explicit_target_inclusion(self):
        number,picture=self.add_bottle(); original=self.view()
        bottle_id=original['unit_ids'][str(number)]; person_id=original['unit_ids']['1']
        self.cut=self.new_cut(new_scene=True)
        response=self.client.post(f'/api/cuts/{self.cut}/reuse',json=self.command(kind='unit',reference_id=bottle_id,slots={picture:6}))
        self.assertEqual(response.status_code,200,response.text)
        view=response.json(); bottle=view['draft_input']['active_units'][0]
        self.assertEqual(bottle['subject'],1)
        self.assertIsNone(bottle['scale']['reference_subject'])
        self.assertEqual(bottle['scale']['reference_subject_id'],person_id)
        self.assertEqual(len(view['draft_input']['active_units']),1)
        self.assertTrue(any('confronto dimensionale' in issue for issue in view['catalogue_issues']))
        response=self.client.post(f'/api/cuts/{self.cut}/reuse',json=self.command(kind='unit',reference_id=person_id,slots={}))
        self.assertEqual(response.status_code,200,response.text)
        raw=response.json()['draft_input']; bottle=raw['active_units'][0]
        self.assertEqual(bottle['scale']['reference_subject'],2)
        raw['request']='<Subject 1> rimane sul tavolo.'
        raw['pictures'][0]['linked_to_h3']=True
        prompt=render(CompileInput.model_validate(raw),plan(),'reused').prompt
        self.assertIn('relative to <Subject 2> as shown in <Picture 6>',prompt)
        self.assertEqual(self.fake.calls,0)

    def test_identity_mismatch_rejected_and_incomplete_draft_remains_saveable(self):
        self.add_bottle(); raw=self.view()['draft_input']
        raw['active_units'][-1]['scale']['reference_subject_id']=self.view()['unit_ids']['2']
        response=self.client.put(f'/api/cuts/{self.cut}/draft',json=self.command(input=raw))
        self.assertEqual(response.status_code,422,response.text)
        raw=self.view()['draft_input']; raw['active_units'][-1]['scale']['comparison']=''
        view=self.save(raw)
        self.assertTrue(any('confronto dimensionale' in issue for issue in view['catalogue_issues']))
        response=self.client.post(f'/api/cuts/{self.cut}/compile',json=self.command(cut_id=self.cut,input=raw,model='local-test'))
        self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(self.fake.calls,0)

    def test_inheritance_keeps_scale_photo_and_exclusion_blocks_only_included_dependents(self):
        self.add_bottle(second_photo=True); original=self.view()['draft_input']
        self.cut=self.new_cut(inherit=True); raw=self.view()['draft_input']
        self.assertEqual(raw['active_units'][-1]['scale'],original['active_units'][-1]['scale'])
        raw['pictures'][-1]['excluded']=True
        for picture in raw['pictures']:picture['linked_to_h3']=True
        raw['request']='<Subject 1> guarda la camera.'
        view=self.save(raw)
        self.assertTrue(any('riferimento dimensionale usa una Picture esclusa' in issue for issue in view['catalogue_issues']))
        raw['active_units'][-1]['excluded']=True
        self.save(raw)
        self.assertNotIn('scales',model_context(CompileInput.model_validate(raw)))

    def test_changed_scale_requires_manual_reconciliation(self):
        self.add_bottle(); version=self.compile()
        raw=self.view()['draft_input']; raw['active_units'][-1]['scale']['measurements']='alta 25 cm'
        self.save(raw)
        response=self.client.put(f'/api/cuts/{self.cut}/manual',json=self.command(text=version['text'],base_candidate_id=version['id']))
        self.assertEqual(response.status_code,200,response.text)
        manual=response.json()['versions'][-1]
        response=self.client.post(f'/api/cuts/{self.cut}/confirm',json=self.command(version_id=manual['id']))
        self.assertEqual(response.status_code,409,response.text)
        self.assertEqual(response.json()['detail']['code'],'reference_reconciliation_required')

    def test_scale_only_photo_is_required_when_reusing_from_library(self):
        number,picture=self.add_bottle(reference=False,second_photo=True); original=self.view()
        self.cut=self.new_cut(new_scene=True)
        slots={p['id']:slot for p,slot in zip(original['draft_input']['pictures'],[4,8])}
        response=self.client.post(f'/api/cuts/{self.cut}/reuse',json=self.command(kind='unit',reference_id=original['unit_ids'][str(number)],slots=slots))
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual({p['id'] for p in response.json()['draft_input']['pictures']},set(slots))
        self.assertEqual(response.json()['draft_input']['active_units'][0]['scale']['picture_id'],picture)

    def test_dedicated_role_survives_library_reuse_and_snapshot(self):
        number,picture=self.add_bottle(reference=False,second_photo=True)
        raw=self.view()['draft_input'];raw['pictures'][-1]['role']='scale_reference';self.save(raw)
        original=self.view();version=self.compile()
        self.assertEqual(version['input_snapshot']['pictures'][-1]['role'],'scale_reference')
        self.assertIn('as shown in <Picture 2>',version['text'])
        self.cut=self.new_cut(new_scene=True)
        slots={p['id']:slot for p,slot in zip(original['draft_input']['pictures'],[4,8])}
        response=self.client.post(f'/api/cuts/{self.cut}/reuse',json=self.command(kind='unit',reference_id=original['unit_ids'][str(number)],slots=slots))
        self.assertEqual(response.status_code,200,response.text)
        raw=response.json()['draft_input']
        self.assertEqual(next(p for p in raw['pictures'] if p['id']==picture)['role'],'scale_reference')
        self.assertEqual(len(raw['active_units']),1)

    def test_selected_context_keeps_historical_scale_without_reverting_library(self):
        self.add_bottle(); version=self.compile(); original=self.cut
        raw=self.view()['draft_input']; raw['active_units'][-1]['scale']['measurements']='alta 25 cm'
        self.save(raw)
        project=self.view()['project_id']
        before=self.client.get(f'/api/projects/{project}/library').json()['units']
        self.cut=self.new_cut()
        raw=self.view()['draft_input']; raw['continuity']=dict(mode='latent',declared_state='La bottiglia è sul tavolo.',previous_cut_id=original,previous_version_id=version['id'])
        self.save(raw)
        response=self.client.post(f'/api/cuts/{self.cut}/context-subject',json=self.command(subject=2))
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['draft_input']['active_units'][0]['scale']['measurements'],scale()['measurements'])
        after=self.client.get(f'/api/projects/{project}/library').json()['units']
        self.assertEqual(before,after)
        self.assertEqual(self.fake.calls,1)


if __name__=='__main__':unittest.main()
