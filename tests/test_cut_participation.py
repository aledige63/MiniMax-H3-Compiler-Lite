import copy
import json
import unittest
from contextlib import closing
from uuid import uuid4

from pydantic import ValidationError

from app.compiler import StructuralError, render
from app.domain import CompileInput, Interpretation
from app.interpreter import input_hash, model_context
from app.narrative import response_schema
from app.physical import detail_entries
from test_picture_registry import catalogue_input,plan
import test_m2 as m2
import test_m3 as m3


def inactive_input():
    raw=catalogue_input()
    raw['pictures'].append(dict(id='future',slot=3,name='Vaso futuro',role='object',description_en='a brass vase',confirmed=False,excluded=True))
    raw['active_units'].append(dict(subject=2,name='Oggetto futuro',role='object',description_en='future vase',confirmed=False,
        sources=[dict(picture_id='future',attribute='object')],excluded=True))
    return raw


class ParticipationTests(unittest.TestCase):
    def test_excluded_references_stay_in_snapshot_but_leave_context_and_prompt(self):
        raw=inactive_input();data=CompileInput.model_validate(raw)
        self.assertEqual(len(data.active_units),2);self.assertTrue(data.model_dump()['pictures'][2]['excluded'])
        context=json.dumps(model_context(data));prompt=render(data,plan(),'x').prompt
        for text in [context,prompt]:
            for absent in ['brass vase','future vase','<Subject 2>','<Picture 3>']:self.assertNotIn(absent,text)
        self.assertEqual([u.subject for u in data.included_units],[1])
        self.assertEqual([p.id for p in data.active_pictures],['face','skirt'])

    def test_excluded_unfinished_subjects_and_images_do_not_block_compilation(self):
        raw=inactive_input();raw['active_units'][1].update(name='',sources=[],physical_details=[dict(id='p1',description='',body_location='')])
        raw['pictures'][2].update(description_en='',analysis=dict(category='invalid'))
        data=CompileInput.model_validate(raw)
        self.assertEqual(detail_entries(data),{})
        self.assertEqual(render(data,plan(),'x').status,'proposal')
        self.assertEqual(data.model_dump()['active_units'][1]['physical_details'][0]['description'],'')

    def test_subject_exclusion_automatically_omits_its_unshared_images(self):
        raw=inactive_input();raw['pictures'][2].pop('excluded')
        data=CompileInput.model_validate(raw)
        self.assertNotIn('future', [p.id for p in data.active_pictures])
        self.assertNotIn('brass vase',json.dumps(model_context(data)))
        raw['active_units'][1]['sources']=[dict(picture_id='face',attribute='object')]
        self.assertIn('face',[p.id for p in CompileInput.model_validate(raw).active_pictures])

    def test_included_subject_cannot_use_an_excluded_picture_or_detail_picture(self):
        raw=inactive_input();raw['pictures'][0]['excluded']=True
        with self.assertRaises(ValidationError) as exc:CompileInput.model_validate(raw)
        self.assertIn('esclusa',str(exc.exception))
        raw=inactive_input();raw['active_units'][0]['physical_details']=[dict(id='p1',description='un dettaglio',body_location='mano',operation='add',picture_id='future')]
        with self.assertRaises(ValidationError) as exc:CompileInput.model_validate(raw)
        self.assertIn('immagine esclusa',str(exc.exception))

    def test_request_speaker_and_camera_cannot_refer_to_excluded_subjects(self):
        for key in ['request','dialogue','camera']:
            raw=inactive_input()
            if key=='request':raw['request']='<Subject 2> enters.'
            elif key=='dialogue':raw['dialogues']=[dict(id='d1',text='Ciao.',language='Italian',speaker_subject=2,confirmed=True)]
            else:raw['camera']=dict(framing='close-up',subject=2)
            with self.subTest(key=key),self.assertRaises(ValidationError):CompileInput.model_validate(raw)

    def test_excluded_guide_does_not_require_an_event_or_description(self):
        raw=inactive_input();raw['pictures'][2].update(role='style',guidance=dict(enabled=True),description_en='')
        data=CompileInput.model_validate(raw)
        self.assertEqual(data.active_picture_guides,[])
        self.assertNotIn('GuidePart',json.dumps(response_schema(data)['anyOf'][0]['properties']['narrative_parts']))
        self.assertEqual(render(data,plan(),'x').status,'proposal')

    def test_default_false_keeps_historical_hashes_and_serialization(self):
        original=CompileInput.model_validate(catalogue_input());raw=original.model_dump()
        for row in raw['pictures']+raw['active_units']:row['excluded']=False
        current=CompileInput.model_validate(raw)
        self.assertEqual(current.model_dump(),original.model_dump());self.assertEqual(input_hash(current),input_hash(original))
        for value in [1,'true',None]:
            raw['active_units'][0]['excluded']=value
            with self.subTest(value=value),self.assertRaises(ValidationError):CompileInput.model_validate(raw)

    def test_renderer_rejects_model_reintroducing_excluded_reference(self):
        data=CompileInput.model_validate(inactive_input())
        wrong=Interpretation(narrative_en='<Subject 2> enters.',estimated_duration_s=5.,question=None)
        with self.assertRaises(StructuralError):render(data,wrong,'x')

    def test_excluded_ids_and_slots_are_still_reserved(self):
        raw=inactive_input();raw['pictures'][2]['slot']=1
        with self.assertRaises(ValidationError):CompileInput.model_validate(raw)


class ParticipationApiTests(unittest.TestCase):
    tearDown=m3.M3ApiTests.tearDown
    view=m3.M3ApiTests.view
    command=m3.M3ApiTests.command
    save=m3.M3ApiTests.save
    completed=m2.M2Tests.completed
    create_cut=m2.M2Tests.create_cut
    cut_command=m2.M2Tests.cut_command

    def setUp(self):
        m3.M3ApiTests.setUp(self)
        for kind in ['picture','picture','unit','unit']:
            response=self.client.post(f'/api/cuts/{self.cut}/items',json=self.command(kind=kind));self.assertEqual(response.status_code,200,response.text)
        raw=self.view()['draft_input'];raw['request']='<Subject 1> resta immobile.'
        for p,name,role,description in zip(raw['pictures'],['Persona','Vaso'],['identity','object'],['a person with brown hair','a brass vase']):
            p.update(name=name,role=role,description_en=description,confirmed=True,linked_to_h3=True)
        for u,p,role in zip(raw['active_units'],raw['pictures'],['character','object']):
            u.update(name=p['name'],role=role,confirmed=True,sources=[dict(attribute='identity' if role=='character' else 'object',picture_id=p['id'])])
        self.save(raw)
        self.fake.plan=Interpretation(narrative_en='<Subject 1> remains still.',summary_en='<Subject 1> remains still.',estimated_duration_s=5.,question=None)

    def exclude(self):
        raw=self.view()['draft_input'];raw['active_units'][1]['excluded']=True;raw['pictures'][1]['excluded']=True
        self.save(raw);return raw

    def compile(self,raw):
        response=self.client.post(f'/api/cuts/{self.cut}/compile',json=self.command(cut_id=self.cut,input=raw,model='text-test'))
        self.assertEqual(response.status_code,202,response.text);return self.completed(response.json())

    def test_flags_are_local_to_cut_and_do_not_change_canonical_revisions(self):
        before=self.view();project=before['project_id'];library=self.client.get(f'/api/projects/{project}/library').json()
        self.exclude();after=self.client.get(f'/api/projects/{project}/library').json()
        self.assertEqual(library,after);self.assertEqual(self.fake.calls,0)
        self.assertEqual(self.view()['unit_ids'],before['unit_ids'])
        self.assertEqual(self.view()['reference_revisions'],before['reference_revisions'])
        self.assertEqual(self.view()['unit_revisions'],before['unit_revisions'])
        self.assertNotIn('2',[token['id'] for token in self.view()['tokens'] if token['kind']=='unit'])

    def test_compilation_keeps_full_snapshot_and_hash_but_omits_excluded_references(self):
        raw=self.exclude();job=self.compile(raw);self.assertEqual(job['status'],'succeeded',job)
        self.assertNotIn('<Subject 2>',job['result']['prompt']);self.assertNotIn('<Picture 2>',job['result']['prompt']);self.assertNotIn('brass vase',job['result']['prompt'])
        snapshot=self.view()['versions'][-1]['input_snapshot']
        self.assertTrue(snapshot['active_units'][1]['excluded']);self.assertTrue(snapshot['pictures'][1]['excluded'])
        self.assertEqual(job['input_hash'],input_hash(CompileInput.model_validate(raw)));self.assertEqual(self.fake.calls,1)

    def test_excluded_missing_media_is_preserved_in_snapshot_without_blocking_compile(self):
        id=self.view()['draft_input']['pictures'][1]['id']
        media=self.client.post('/api/media',content=m2.png()).json()
        self.client.put(f'/api/cuts/{self.cut}/pictures/{id}/media',json=self.command(media_id=media['id']))
        with closing(self.app.state.repository.connect()) as db:
            path=self.app.state.repository.directory/db.execute('SELECT relative_path FROM media WHERE id=?',(media['id'],)).fetchone()[0]
        path.unlink()  # Solo il file sintetico dell’archivio temporaneo.
        raw=self.exclude();job=self.compile(raw);self.assertEqual(job['status'],'succeeded',job)
        self.assertIn(id,self.view()['versions'][-1]['media_snapshot'])
        version_id=self.view()['versions'][-1]['id']
        self.assertFalse(any('media' in issue.lower() for issue in self.view()['confirmation_issues'][version_id]))

    def test_inheritance_keeps_choice_but_library_reuse_is_included_by_default(self):
        raw=self.exclude();project=self.client.get('/api/projects').json()[0];scene=project['scenes'][0]
        response=self.client.post(f"/api/scenes/{scene['id']}/cuts",json=dict(command_id=str(uuid4()),expected_revision=scene['revision'],name='Segue',inherit_references=True))
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['draft_input']['active_units'][1]['excluded'])
        other=self.create_cut();unit_id=self.view()['unit_ids']['2'];pic=raw['pictures'][1]['id']
        response=self.client.post(f'/api/cuts/{other}/reuse',json=self.cut_command(other,kind='unit',reference_id=unit_id,slots={pic:4}))
        self.assertEqual(response.status_code,200,response.text)
        self.assertFalse(response.json()['draft_input']['active_units'][0].get('excluded',False))

    def test_reloading_from_library_preserves_existing_exclusion(self):
        raw=self.exclude();unit_id=self.view()['unit_ids']['2'];pic=raw['pictures'][1]['id']
        for kind,id in [('picture',pic),('unit',unit_id)]:
            response=self.client.post(f'/api/cuts/{self.cut}/reuse',json=self.command(kind=kind,reference_id=id,slots={}))
            self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(self.view()['draft_input']['active_units'][1]['excluded'])
        self.assertTrue(self.view()['draft_input']['pictures'][1]['excluded'])

    def test_reenable_restores_existing_numbers_and_keeps_old_snapshot_exact(self):
        raw=self.exclude();self.compile(raw);saved=copy.deepcopy(self.view()['versions'])
        raw=self.view()['draft_input']
        for row in raw['active_units']+raw['pictures']:row.pop('excluded',None)
        self.save(raw)
        self.assertEqual(self.view()['versions'],saved)
        self.assertEqual([u['subject'] for u in raw['active_units']],[1,2])
        self.assertEqual([p['slot'] for p in raw['pictures']],[1,2])


if __name__=='__main__':unittest.main()
