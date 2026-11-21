import copy
import json
import sqlite3
import tempfile
import unittest
from uuid import uuid4
from pydantic import ValidationError
from fastapi.testclient import TestClient
from app.api import create_app

from app.compiler import render, StructuralError
from app.domain import CompileInput, CurrentInterpretation
from app.interpreter import model_context
from app.repository import Repository
from app.contracts import WebCompileCommand
from app.store import digest
from test_api import FakeOllama
from test_picture_registry import catalogue_input


def picture(id='map',slot=3,role='initial_composition',**guidance):
    return dict(id=id,slot=slot,name='Guide',role=role,description_en='two simplified figures in a room',confirmed=True,linked_to_h3=True,guidance=dict(enabled=True,**guidance))


def video(id='v1',slot=1,role='camera',**guidance):
    return dict(id=id,slot=slot,name='Guide',role=role,description_en='the declared guide',duration_s=5.0,duration_origin='declared',file_exists=True,confirmed=True,linked_to_h3=True,guidance=dict(enabled=True,**guidance))


def plan(narrative='<Subject 1> waits.'):
    return CurrentInterpretation(narrative_en=narrative,summary_en='<Subject 1> waits in the scene.',estimated_duration_s=6.0,question=None)


class M5DomainTests(unittest.TestCase):
    def test_camera_choices_are_optional_distinct_and_share_the_model_narrative(self):
        raw=catalogue_input();data=CompileInput.model_validate(raw)
        self.assertNotIn('camera_direction',model_context(data))
        raw['camera']=dict(framing='american',angle='dutch',movement='push_in',amplitude='small',speed='slow',subject=1,placement='as_requested')
        context=model_context(CompileInput.model_validate(raw))['camera_direction']
        self.assertEqual(context['movement'],'pushes in');self.assertIn('knees',context['framing']);self.assertEqual(context['angle'],'Dutch angle')
        self.assertEqual(context['speed'],'at slow speed')
        for change in [dict(movement='unknown'),dict(movement='static',speed='fast'),dict(movement=None,amplitude='large'),dict(subject=9),dict(placement='after_dialogue',dialogue_id='missing')]:
            with self.subTest(change=change),self.assertRaises(ValidationError):CompileInput.model_validate(raw|{'camera':raw['camera']|change})

    def test_camera_after_dialogue_has_explicit_id_without_repeating_words(self):
        raw=catalogue_input();raw['dialogues']=[dict(id='d1',text='PRIVATE_WORDS',language='Italian',speaker_subject=1,confirmed=True)]
        raw['camera']=dict(movement='tracking',placement='after_dialogue',dialogue_id='d1',subject=1)
        context=model_context(CompileInput.model_validate(raw));self.assertEqual(context['camera_direction']['dialogue_id'],'d1');self.assertNotIn('PRIVATE_WORDS',json.dumps(context))

    def test_initial_composition_mapping_is_not_a_new_subject_or_frame_anchor(self):
        raw=catalogue_input();raw['pictures'].append(picture(mappings=[dict(figure='the left figure',subject=1)]))
        data=CompileInput.model_validate(raw);context=model_context(data)
        self.assertEqual(len(context['active_references']),1)
        self.assertEqual(context['direction_guides'][0]['placeholder'],'{{guide:picture_3}}')
        prompt=render(data,plan('{{guide:picture_3}} <Subject 1> waits.'),'composition').prompt
        self.assertIn('Use <Picture 3> for the initial composition.',prompt)
        self.assertIn('"the left figure" identifies <Subject 1>',prompt)
        self.assertNotIn('keyframe completion',prompt);self.assertNotIn('<Subject 2>',prompt)

    def test_inactive_guides_are_not_sent_and_can_retain_incomplete_mapping(self):
        raw=catalogue_input();raw['pictures'].append(picture(mappings=[dict(figure='',subject=None)]));raw['pictures'][-1].update(confirmed=False,linked_to_h3=False)
        raw['pictures'][-1]['guidance']['enabled']=False
        raw['videos']=[video(mappings=[])];raw['videos'][0]['guidance']['enabled']=False
        data=CompileInput.model_validate(raw)
        self.assertNotIn('direction_guides',model_context(data));self.assertNotIn('<Video',render(data,plan(),'unused').prompt)
        self.assertNotIn('<Picture 3>',render(data,plan(),'unused').prompt)

    def test_maps_require_marks_and_do_not_assign_camera_to_subject(self):
        raw=catalogue_input();raw['pictures'].append(picture(role='spatial_map',mappings=[]))
        for mapping in [[],[dict(figure='red circle',role='start')],[dict(figure='camera mark',role='camera_start',subject=1)],[dict(figure='figure',subject=99)]]:
            raw['pictures'][-1]['guidance']['mappings']=mapping
            with self.subTest(mapping=mapping),self.assertRaises(ValidationError):CompileInput.model_validate(raw)
        raw['pictures'][-1]['guidance']['mappings']=[dict(figure='red circle',role='start',subject=1),dict(figure='black arrow',role='camera_direction')]
        data=CompileInput.model_validate(raw);prompt=render(data,plan('{{guide:picture_3}} <Subject 1> waits.'),'map').prompt
        self.assertIn('starting position of <Subject 1>',prompt);self.assertIn('the camera direction',prompt)
        raw['pictures'][-1]['guidance']['mappings'].append(dict(figure='RED CIRCLE',role='destination',subject=1))
        with self.assertRaises(ValidationError):CompileInput.model_validate(raw)

    def test_guides_cannot_be_disguised_as_identity_pictures(self):
        raw=catalogue_input();raw['pictures'][0].update(role='style',guidance=dict(enabled=True));
        with self.assertRaises(ValidationError):CompileInput.model_validate(raw)

    def test_verbatim_guide_prompt_is_inserted_once_and_not_replaced_by_a_second_narrative(self):
        raw=catalogue_input();raw['pictures'].append(picture(role='style',prompt_en='  Use a restrained watercolor palette.\nKeep visible paper grain.  '))
        data=CompileInput.model_validate(raw);prompt=render(data,plan('{{guide:picture_3}} <Subject 1> waits.'),'verbatim').prompt
        self.assertEqual(prompt.count(raw['pictures'][-1]['guidance']['prompt_en']),1)
        self.assertEqual(prompt.split('detailed_description:\n')[1].count('[Shot 1] '),1);self.assertIn('weak_reference',prompt)
        for narrative in ['<Subject 1> waits.','{{guide:picture_3}} {{guide:picture_3}} <Subject 1> waits.','{{guide:picture_9}} <Subject 1> waits.','<Subject 1> reaches the frame indicated by {{guide:picture_3}}.']:
            with self.subTest(narrative=narrative),self.assertRaises(StructuralError):render(data,plan(narrative),'bad')
        for prompt_en in ['<d>[Italian] Added speech</d>', 'summary: new section', '{{dialogue:d1}}', '<Subject 99> moves.', '<Picture 99> guides.', '<Subject']:
            raw['pictures'][-1]['guidance']['prompt_en']=prompt_en
            with self.subTest(prompt_en=prompt_en),self.assertRaises(ValidationError):CompileInput.model_validate(raw)

    def test_camera_guide_combines_with_framing_but_not_second_camera_motion_source(self):
        raw=catalogue_input();raw['videos']=[video()];raw['camera']=dict(framing='full',angle='low')
        data=CompileInput.model_validate(raw);prompt=render(data,plan('{{camera:main}} <Subject 1> waits. {{guide:video_1}}'),'camera').prompt
        self.assertIn('Use only the camera movement from <Video 1>.',prompt)
        self.assertIn('[reference generation]',prompt);self.assertNotIn('video continuation',prompt);self.assertNotIn('The video continues',prompt)
        self.assertNotIn('continuity context of <Video',prompt)
        raw['camera']['movement']='static'
        with self.assertRaises(ValidationError):CompileInput.model_validate(raw)

    def test_combined_guide_consumes_one_slot_and_motion_maps_are_explicit(self):
        raw=catalogue_input();raw['videos']=[video(role='camera_and_subject_motion',mappings=[dict(figure='the mannequin',role='motion',subject=1)])]
        data=CompileInput.model_validate(raw);self.assertEqual(len(data.active_videos),1)
        prompt=render(data,plan('{{guide:video_1}} <Subject 1> waits.'),'combined').prompt
        self.assertIn('camera movement and mapped Subject motion',prompt);self.assertIn('no appearance, background or audio transfer',prompt)
        raw['videos'][0]['guidance']['mappings']=[]
        with self.assertRaises(ValidationError):CompileInput.model_validate(raw)
        raw['videos'][0]['guidance']['mappings']=[dict(figure='the mannequin',role='figure',subject=1)]
        with self.assertRaises(ValidationError):CompileInput.model_validate(raw)

    def test_all_active_videos_share_total_duration_with_continuation(self):
        raw=catalogue_input();continuation=video();continuation.update(role='continuation',guidance=None,duration_s=10.0)
        raw['videos']=[continuation,video(id='v2',slot=2)];raw['continuity']=dict(mode='video_reference',declared_state='<Subject 1> è ferma.',video_id='v1')
        data=CompileInput.model_validate(raw);prompt=render(data,plan('{{guide:video_2}} <Subject 1> waits.'),'both').prompt
        self.assertIn('The video continues from <Video 1>.',prompt);self.assertIn('Use only the camera movement from <Video 2>.',prompt)
        raw['videos'][1]['duration_s']=6.0
        with self.assertRaises(ValidationError):CompileInput.model_validate(raw)
        raw['videos'][1]['duration_s']=1.0
        with self.assertRaises(ValidationError):CompileInput.model_validate(raw)

    def test_motion_sources_cannot_double_control_same_subject(self):
        raw=catalogue_input();raw['videos']=[video(role='subject_motion',mappings=[dict(figure='figure',role='motion',subject=1)]),video(id='v2',slot=2,role='subject_motion',mappings=[dict(figure='other figure',role='motion',subject=1)])]
        with self.assertRaises(ValidationError):CompileInput.model_validate(raw)

    def test_frame_anchor_is_explicit_has_workflow_and_checks_keyframe_duration(self):
        raw=catalogue_input();raw['pictures'].append(picture(role='frame_anchor'))
        with self.assertRaises(ValidationError):CompileInput.model_validate(raw)
        g=raw['pictures'][-1]['guidance'];g.update(anchor='first',workflow='declared Ref2VA anchor workflow')
        prompt=render(CompileInput.model_validate(raw),plan('{{guide:picture_3}} <Subject 1> waits.'),'first').prompt
        self.assertIn('The shot begins from <Picture 3>.',prompt);self.assertIn('keyframe completion',prompt)
        g.update(anchor='keyframe',at_s=7.0)
        result=render(CompileInput.model_validate(raw),plan('<Subject 1> waits. {{guide:picture_3}}'),'late-keyframe')
        self.assertFalse(result.confirmation_allowed)
        g.update(anchor='last',at_s=None);raw['continuity']=dict(mode='latent',declared_state='<Subject 1> è ferma.',seamless=True)
        with self.assertRaises(ValidationError):CompileInput.model_validate(raw)
        g['continuity_checked']=True;CompileInput.model_validate(raw)

    def test_new_defaults_preserve_old_receipt_hash_but_active_camera_is_a_new_command(self):
        with tempfile.TemporaryDirectory() as folder:
            repo=Repository(folder);cut=repo.workspace().id
            command=WebCompileCommand.model_validate_json(json.dumps(dict(command_id=str(uuid4()),cut_id=str(cut),expected_revision=0,input=catalogue_input(),model='fixture')))
            old=command.model_dump(mode='json');old['input'].pop('camera')
            for p in old['input']['pictures']:p.pop('guidance')
            fingerprint=digest(dict(operation='compile',cut_id=str(cut),command=old))
            self.assertIn(fingerprint,repo._receipt_hashes('compile',cut,command))
            changed=command.model_copy(update={'input':CompileInput.model_validate(command.input.model_dump()|{'camera':dict(movement='zoom_in')})})
            self.assertNotIn(fingerprint,repo._receipt_hashes('compile',cut,changed))


class M5ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.fake=FakeOllama();self.fake.plan=plan()
        self.app=create_app(self.temp.name,self.fake);self.client=TestClient(self.app,base_url='http://127.0.0.1:8767');self.client.__enter__()
        self.cut=self.client.get('/api/workspace').json()['id']
        for kind in ['picture','unit']:
            current=self.client.post(f'/api/cuts/{self.cut}/items',json=self.command(kind=kind)).json()
        self.raw=current['draft_input'];p=self.raw['pictures'][0]
        p.update(name='Identity',description_en='a woman with brown hair',confirmed=True,linked_to_h3=True)
        self.raw['active_units'][0].update(name='Ann',description_en='Ann',confirmed=True,sources=[dict(picture_id=p['id'],attribute='identity')])
        self.raw.update(request='<Subject 1> resta ferma.',declared_duration_s=6.0);self.save(self.raw)
    def tearDown(self):self.client.__exit__(None,None,None);self.temp.cleanup()
    def view(self):return self.client.get(f'/api/cuts/{self.cut}').json()
    def command(self,**extra):return dict(command_id=str(uuid4()),expected_revision=self.view()['revision'],**extra)
    def save(self,raw):
        response=self.client.put(f'/api/cuts/{self.cut}/draft',json=self.command(input=raw));self.assertEqual(response.status_code,200,response.text);return response.json()
    def compile(self,expected=202):
        response=self.client.post(f'/api/cuts/{self.cut}/compile',json=self.command(cut_id=self.cut,input=self.view()['draft_input'],model='local-test'))
        self.assertEqual(response.status_code,expected,response.text)
        if expected!=202:return response
        self.app.state.worker.pending.join();return self.view()['versions'][-1]
    def add_guide_picture(self,**usage):
        view=self.client.post(f'/api/cuts/{self.cut}/items',json=self.command(kind='picture')).json();self.raw=view['draft_input'];p=self.raw['pictures'][-1]
        p.update(role='initial_composition',name='Composition',description_en='one simplified figure on the left',confirmed=True,linked_to_h3=True,guidance=dict(enabled=True,mappings=[dict(figure='the left figure',subject=1)],**usage))
        self.save(self.raw);return p

    def test_camera_persists_in_snapshot_and_has_no_inference_on_save(self):
        raw=self.view()['draft_input'];raw['camera']=dict(framing='full',angle='low',movement='push_in',speed='slow');self.save(raw)
        self.fake.plan=plan('{{camera:main}} <Subject 1> waits.')
        self.assertEqual(self.fake.calls,0);version=self.compile()
        self.assertEqual(version['input_snapshot']['camera']['movement'],'push_in');self.assertEqual(self.fake.calls,1)
        reopened=Repository(self.temp.name).workspace(self.cut)
        self.assertEqual(reopened.draft_input['camera']['framing'],'full')
        self.assertEqual(reopened.versions[-1].text,version['text'])

    def test_invalid_camera_is_rejected_before_any_inference_with_useful_error(self):
        raw=self.view()['draft_input'];raw['camera']=dict(movement='static',speed='fast');self.save(raw)
        response=self.compile(422);self.assertIn('Ampiezza e velocità',response.text);self.assertEqual(self.fake.calls,0)

    def test_video_guide_managed_file_has_real_hash_snapshot_without_continuation(self):
        from test_m4 import video_bytes
        created=self.client.post(f'/api/cuts/{self.cut}/items',json=self.command(kind='video')).json();id=created['draft_input']['videos'][0]['id']
        uploaded=self.client.post('/api/video-media',content=video_bytes()).json()
        attached=self.client.put(f'/api/cuts/{self.cut}/videos/{id}/media',json=self.command(media_id=uploaded['id'])).json()
        raw=attached['draft_input'];raw['videos'][0].update(role='camera',confirmed=True,linked_to_h3=True,guidance=dict(enabled=True),description_en='a slow camera push')
        self.save(raw);self.fake.plan=plan('<Subject 1> waits. {{guide:video_1}}');version=self.compile()
        self.assertEqual(version['media_snapshot']['video:'+id]['sha256'],uploaded['sha256'])
        self.assertNotIn('video continuation',version['text']);self.assertNotIn('<Audio',version['text'])
        self.assertIn('Use only the camera movement from <Video 1>.',version['text'])

    def test_guide_mapping_is_per_cut_not_project_library_and_versions_are_immutable(self):
        p=self.add_guide_picture(prompt_en='Keep the declared figure spacing.')
        self.fake.plan=plan('{{guide:picture_2}} <Subject 1> waits.');first=self.compile()
        library=self.client.get(f"/api/projects/{self.view()['project_id']}/library").json()
        stored=next(item for item in library['pictures'] if item['id']==p['id']);self.assertNotIn('guidance',stored)
        raw=self.view()['draft_input'];raw['pictures'][-1]['guidance']['mappings'][0]['figure']='the central figure';self.save(raw)
        self.assertEqual(self.client.get(f"/api/cuts/{self.cut}/text?version_id={first['id']}").text,first['text'])
        self.assertEqual(first['input_snapshot']['pictures'][-1]['guidance']['mappings'][0]['figure'],'the left figure')

    def test_old_snapshot_neutral_defaults_still_confirm_without_rewriting_version(self):
        first=self.compile();historical=copy.deepcopy(first);snapshot=historical['input_snapshot'];snapshot.pop('camera',None)
        for p in snapshot['pictures']:p.pop('guidance',None)
        historical['input_hash']=digest(snapshot)
        with self.app.state.repository.transaction() as db:db.execute('UPDATE versions SET data=? WHERE id=?',(json.dumps(historical),first['id']))
        response=self.client.post(f'/api/cuts/{self.cut}/confirm',json=self.command(version_id=first['id']))
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['state'],'confirmed')
        self.assertEqual(response.json()['versions'][-1]['input_snapshot'],snapshot)
        self.assertEqual(response.json()['versions'][-1]['text'],first['text'])

    def test_changed_guide_mapping_requires_explicit_reference_acknowledgement(self):
        self.add_guide_picture();self.fake.plan=plan('{{guide:picture_2}} <Subject 1> waits.');first=self.compile()
        raw=self.view()['draft_input'];raw['pictures'][-1]['guidance']['mappings'][0]['figure']='the right figure';self.save(raw)
        response=self.client.post(f'/api/cuts/{self.cut}/confirm',json=self.command(version_id=first['id']))
        self.assertEqual(response.status_code,409,response.text);self.assertEqual(response.json()['detail']['code'],'reference_reconciliation_required')
        response=self.client.post(f'/api/cuts/{self.cut}/confirm',json=self.command(version_id=first['id'],acknowledge_reference_changes=True))
        self.assertEqual(response.status_code,200,response.text)
        self.assertIn('"the left figure"',response.json()['versions'][-1]['text'])

    def test_changed_guide_role_requires_acknowledgement_even_with_identical_mapping(self):
        self.add_guide_picture();self.fake.plan=plan('{{guide:picture_2}} <Subject 1> waits.');first=self.compile()
        raw=self.view()['draft_input'];raw['pictures'][-1]['role']='composition_previz';self.save(raw)
        response=self.client.post(f'/api/cuts/{self.cut}/confirm',json=self.command(version_id=first['id']))
        self.assertEqual(response.status_code,409,response.text)
        self.assertEqual(response.json()['detail']['code'],'reference_reconciliation_required')

    def test_reload_guide_description_keeps_local_mapping_and_requires_reconfirmation(self):
        p=self.add_guide_picture(prompt_en='Keep the declared spacing.')
        self.fake.plan=plan('{{guide:picture_2}} <Subject 1> waits.');first=self.compile()
        raw=self.view()['draft_input'];usage=copy.deepcopy(raw['pictures'][-1]['guidance'])
        raw['pictures'][-1]['description_en']='one simplified figure beside a blue rectangle';self.save(raw)
        response=self.client.post(f'/api/cuts/{self.cut}/reuse',json=self.command(kind='picture',reference_id=p['id'],slots={}))
        self.assertEqual(response.status_code,200,response.text)
        view=response.json();reloaded=view['draft_input']['pictures'][-1]
        self.assertEqual(reloaded['guidance'],usage)
        self.assertFalse(reloaded['confirmed']);self.assertFalse(reloaded['linked_to_h3'])
        self.assertEqual(reloaded['description_en'],raw['pictures'][-1]['description_en'])
        self.assertEqual(view['versions'][-1]['text'],first['text']);self.assertEqual(self.fake.calls,1)
