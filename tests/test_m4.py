import copy
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

import av
import numpy as np
from fractions import Fraction
from PIL import Image
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import create_app
from app.compiler import render
from app.domain import CompileInput, Continuity, CurrentInterpretation
from app.interpreter import model_context
from app.repository import Repository
from app.store import digest
from app.contracts import WebCompileCommand
from test_m3 import VisionClient


@lru_cache()
def video_bytes(seconds=3, audio=False):
    output=io.BytesIO()
    with av.open(output,'w',format='mp4') as file:
        stream=file.add_stream('libx264',rate=10); stream.width=160; stream.height=90; stream.pix_fmt='yuv420p'
        sound=file.add_stream('aac',rate=16000) if audio else None
        if sound: sound.layout='mono'
        for n in range(round(seconds*10)):
            frame=av.VideoFrame.from_image(Image.new('RGB',(160,90),(n*5 % 255,40,100)))
            for packet in stream.encode(frame): file.mux(packet)
        for packet in stream.encode(): file.mux(packet)
        if sound:
            for n in range(0,round(seconds*16000),1024):
                frame=av.AudioFrame.from_ndarray(np.zeros((1,min(1024,round(seconds*16000)-n)),dtype='float32'),format='fltp',layout='mono')
                frame.sample_rate=16000;frame.pts=n;frame.time_base=Fraction(1,16000)
                for packet in sound.encode(frame):file.mux(packet)
            for packet in sound.encode():file.mux(packet)
    return output.getvalue()


def context_input(mode='latent'):
    return dict(request='<Subject 1> si alza.',pictures=[],active_units=[dict(subject=1,name='Ann',role='character',
        description_en='Ann',confirmed=True,sources=[dict(origin='context',attribute='identity')])],
        continuity=dict(mode=mode,declared_state='<Subject 1> è seduta.',window_frames=39,trim_frames=12,sampling_prefix_frames=90))


class M4DomainTests(unittest.TestCase):
    def plan(self):
        return CurrentInterpretation(narrative_en='<Subject 1> is seated, then stands up.',summary_en='<Subject 1> stands up from a seated position.',estimated_duration_s=5.0,question=None)

    def test_latent_and_pixel_context_subject_without_fictitious_picture_or_video(self):
        for mode in ['latent','tail_frames']:
            data=CompileInput.model_validate(context_input(mode)); prompt=render(data,self.plan(),'context').prompt
            self.assertIn('identity from the declared continuity context',prompt)
            self.assertNotIn('<Picture',prompt); self.assertNotIn('<Video',prompt)
            self.assertNotIn('39',prompt); self.assertNotIn('90',prompt)
            self.assertEqual(prompt.split('detailed_description:')[1].count('is seated'),1)
            context=model_context(data)
            self.assertEqual(context['continuity']['declared_state'],'<Subject 1> è seduta.')
            self.assertEqual(context['active_references'][0]['sources'][0]['origin'],'declared_continuity_context')
            self.assertNotIn('window_frames',json.dumps(context)); self.assertNotIn('previous_version_id',json.dumps(context))

    def test_context_requires_declared_continuity_and_never_a_picture_identifier(self):
        for edit in ['none','missing_state','picture_id']:
            raw=context_input()
            if edit=='none':raw['continuity']={'mode':'none','declared_state':None}
            if edit=='missing_state':raw['continuity']['declared_state']=''
            if edit=='picture_id':raw['active_units'][0]['sources'][0]['picture_id']='fake'
            with self.subTest(edit=edit),self.assertRaises(ValidationError):CompileInput.model_validate(raw)

    def test_video_reference_is_explicit_and_uses_valid_visual_retention_marker(self):
        raw=context_input('video_reference');raw['continuity']['video_id']='v1'
        raw['videos']=[dict(id='v1',slot=2,duration_s=5.0,file_exists=True,linked_to_h3=True,confirmed=True)]
        data=CompileInput.model_validate(raw);prompt=render(data,self.plan(),'video').prompt
        self.assertIn('<Video 2> is the source clip',prompt)
        self.assertIn('from the continuity context of <Video 2>',prompt)
        self.assertIn('[video continuation]',prompt);self.assertNotIn('<Picture',prompt)
        self.assertIn('<Video 2> (continuation source): fully_preserved',prompt)
        self.assertIn('[Shot 1] The video continues from <Video 2>. <Subject 1> is seated',prompt)
        self.assertNotIn('<Audio',prompt);self.assertEqual(model_context(data)['continuity']['source_video'],'<Video 2>')

    def test_unselected_video_stays_out_of_prompt_and_unknown_video_tokens_block(self):
        raw=context_input();raw['videos']=[dict(id='v1',slot=1)]
        data=CompileInput.model_validate(raw)
        self.assertNotIn('videos',model_context(data));self.assertNotIn('<Video',render(data,self.plan(),'unused').prompt)
        raw['request']+=' <Video 1>'
        with self.assertRaises(ValidationError):CompileInput.model_validate(raw)

    def test_video_confirmation_duration_and_slots_are_checked_before_inference(self):
        for edit in ['missing','unconfirmed','unlinked','nonexistent','short','long','duplicate']:
            raw=context_input('video_reference');raw['continuity']['video_id']='v1'
            raw['videos']=[dict(id='v1',slot=1,duration_s=5.0,file_exists=True,confirmed=True,linked_to_h3=True)]
            if edit=='missing':raw['videos']=[]
            if edit=='unconfirmed':raw['videos'][0]['confirmed']=False
            if edit=='unlinked':raw['videos'][0]['linked_to_h3']=False
            if edit=='nonexistent':raw['videos'][0]['file_exists']=False
            if edit=='short':raw['videos'][0]['duration_s']=1.0
            if edit=='long':raw['videos'][0]['duration_s']=16.0
            if edit=='duplicate':raw['videos'].append(dict(id='v2',slot=1))
            with self.subTest(edit=edit),self.assertRaises(ValidationError):CompileInput.model_validate(raw)

    def test_none_mode_cannot_hide_previous_context_or_workflow_parameters(self):
        for field,value in [('previous_cut_id','past'),('window_frames',39),('seamless',True),('context_media_id','file')]:
            with self.subTest(field=field),self.assertRaises(ValidationError):Continuity.model_validate({'mode':'none',field:value})
        with self.assertRaises(ValidationError):Continuity.model_validate(dict(mode='latent',declared_state='Stanza.',previous_cut_id='past'))


class M4ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.fake=VisionClient()
        self.app=create_app(self.temp.name,self.fake);self.client=TestClient(self.app,base_url='http://127.0.0.1:8767');self.client.__enter__()
        self.cut=self.client.get('/api/workspace').json()['id']
    def tearDown(self):
        self.fake.release.set();self.client.__exit__(None,None,None);self.temp.cleanup()
    def view(self):return self.client.get(f'/api/cuts/{self.cut}').json()
    def command(self,**fields):return dict(command_id=str(uuid4()),expected_revision=self.view()['revision'],**fields)
    def save(self,raw):
        response=self.client.put(f'/api/cuts/{self.cut}/draft',json=self.command(input=raw))
        self.assertEqual(response.status_code,200,response.text);return response.json()
    def media(self,seconds=3):
        response=self.client.post('/api/video-media',content=video_bytes(seconds),headers={'X-File-Name':'not-video.txt','Content-Type':'image/png'})
        self.assertEqual(response.status_code,201,response.text);return response.json()
    def video(self,media=None):
        response=self.client.post(f'/api/cuts/{self.cut}/items',json=self.command(kind='video'))
        self.assertEqual(response.status_code,200,response.text)
        video=response.json()['draft_input']['videos'][-1]
        if media:
            response=self.client.put(f"/api/cuts/{self.cut}/videos/{video['id']}/media",json=self.command(media_id=media['id']))
            self.assertEqual(response.status_code,200,response.text)
        return video['id']
    def compile(self,plan=None):
        self.fake.plan=plan or CurrentInterpretation(narrative_en='An empty room remains still.',summary_en='An empty room remains still.',estimated_duration_s=5.0,question=None)
        raw=self.view()['draft_input'];raw['request']=raw['request'] or 'Una stanza vuota.';self.save(raw)
        command=self.command(cut_id=self.cut,input=raw,model='text-test')
        response=self.client.post(f'/api/cuts/{self.cut}/compile',json=command)
        self.assertEqual(response.status_code,202,response.text);self.app.state.worker.pending.join()
        result=self.client.get('/api/jobs/'+response.json()['id']).json();self.assertEqual(result['status'],'succeeded',result)
        return result,command
    def next_cut(self):
        scene=self.client.get('/api/projects').json()[0]['scenes'][0]
        response=self.client.post(f"/api/scenes/{scene['id']}/cuts",json=dict(command_id=str(uuid4()),expected_revision=scene['revision'],name='Next'))
        self.assertEqual(response.status_code,200,response.text);self.cut=response.json()['id'];return response.json()

    def test_real_video_decode_poster_last_frame_range_and_deduplication(self):
        media=self.media();self.assertEqual(media['duration_s'],3.0);self.assertEqual(media['frame_count'],30);self.assertEqual(media['fps'],10)
        self.assertEqual(self.media()['id'],media['id'])
        first=self.client.get(f"/api/video-media/{media['id']}?frame=first")
        last=self.client.get(f"/api/video-media/{media['id']}?frame=last")
        self.assertEqual(Image.open(io.BytesIO(first.content)).size,(160,90));self.assertNotEqual(first.content,last.content)
        partial=self.client.get(f"/api/video-media/{media['id']}",headers={'Range':'bytes=0-31'})
        self.assertEqual(partial.status_code,206);self.assertEqual(len(partial.content),32)
        self.assertEqual(self.fake.calls,0);self.assertEqual(self.fake.chat_calls,0)

    def test_bad_video_is_rejected_and_durations_cannot_be_forged(self):
        self.assertEqual(self.client.post('/api/video-media',content=b'not a video').status_code,422)
        media=self.media();id=self.video(media)
        raw=self.view()['draft_input'];raw['videos'][0]['duration_s']=9.0
        response=self.client.put(f'/api/cuts/{self.cut}/draft',json=self.command(input=raw))
        self.assertEqual(response.status_code,422)
        raw=self.view()['draft_input'];raw['videos'][0]['media_id']=None
        self.assertEqual(self.client.put(f'/api/cuts/{self.cut}/draft',json=self.command(input=raw)).status_code,422)

    def test_video_slots_are_stable_and_three_is_the_cut_limit(self):
        for _ in range(3):self.video()
        self.assertEqual(self.client.post(f'/api/cuts/{self.cut}/items',json=self.command(kind='video')).status_code,422)
        raw=self.view()['draft_input'];raw['videos'].pop(1);self.save(raw)
        id=self.video();videos=self.view()['draft_input']['videos']
        self.assertEqual([(v['id'],v['slot']) for v in videos],[('v1',1),('v3',3),(id,2)])
        self.assertEqual(id,'v4')

    def test_external_declared_video_needs_no_local_upload_and_adds_no_audio(self):
        id=self.video();raw=self.view()['draft_input']
        raw['continuity']=dict(mode='video_reference',declared_state='Una stanza vuota.',external_source='Video esterno',video_id=id)
        raw['videos'][0].update(duration_s=4.0,file_exists=True,linked_to_h3=True,confirmed=True)
        self.save(raw);job,_=self.compile()
        self.assertIn('<Video 1>',job['result']['prompt']);self.assertNotIn('<Audio',job['result']['prompt'])
        self.assertNotIn('video bytes',json.dumps(self.fake.last_input.model_dump()))

    def test_pixel_context_snapshot_tracks_file_without_video_or_picture_slot(self):
        media=self.media();raw=self.view()['draft_input']
        raw['request']='La stanza resta vuota.';raw['declared_duration_s']=6.0
        raw['continuity']=dict(mode='tail_frames',declared_state='Una stanza vuota.',context_media_id=media['id'],context_media_kind='video',window_frames=39,trim_frames=12,sampling_prefix_frames=90)
        self.save(raw);job,_=self.compile();version=self.view()['versions'][-1]
        self.assertNotIn('<Video',version['text']);self.assertNotIn('<Picture',version['text'])
        self.assertEqual(version['duration_s'],6.0);self.assertEqual(version['media_snapshot']['continuity_context']['sha256'],media['sha256'])
        self.assertEqual(version['input_snapshot']['continuity']['window_frames'],39)
        self.assertNotIn('window_frames',json.dumps(model_context(self.fake.last_input)))
        self.assertEqual(self.view()['context_media']['duration_s'],3.0)

    def test_output_is_bound_to_exact_version_without_rewriting_prompt(self):
        job,_=self.compile();before=self.view()['versions'];media=self.media()
        command=self.command(media_id=media['id'],version_id=job['candidate_id'])
        attached=self.client.put(f'/api/cuts/{self.cut}/output',json=command)
        self.assertEqual(attached.status_code,200,attached.text)
        self.assertEqual(attached.json()['versions'],before)
        self.assertEqual(attached.json()['output_by_version'][job['candidate_id']]['id'],media['id'])
        self.assertEqual(self.client.put(f'/api/cuts/{self.cut}/output',json=command).json(),attached.json())
        self.assertEqual(self.fake.calls,1)
        summary=self.client.get('/api/projects').json()[0]['scenes'][0]['cuts'][0]
        self.assertEqual(summary['duration_s'],5.0);self.assertEqual(summary['output_duration_s'],3.0)

    def test_next_cut_shows_previous_but_inherits_no_state_dialogue_or_audio(self):
        job,_=self.compile();before=self.cut
        current=self.next_cut();self.assertEqual(current['previous_cut']['id'],before)
        self.assertEqual(current['previous_cut']['version']['id'],job['candidate_id'])
        self.assertEqual(current['draft_input']['continuity'],{'mode':'none','declared_state':None})
        for field in ['pictures','active_units','dialogues','audio_references','videos']:
            self.assertEqual(current['draft_input'].get(field,[]),[])

    def test_future_cross_scene_and_wrong_version_provenance_are_rejected(self):
        first=self.cut;job,_=self.compile();version=job['candidate_id']
        self.next_cut();second=self.cut
        raw=self.view()['draft_input'];raw['continuity']=dict(mode='latent',declared_state='Stanza vuota.',previous_cut_id=first,previous_version_id=version)
        self.save(raw)
        self.cut=first;raw=self.view()['draft_input'];raw['continuity']=dict(mode='latent',declared_state='Stanza vuota.',previous_cut_id=second)
        self.assertEqual(self.client.put(f'/api/cuts/{first}/draft',json=self.command(input=raw)).status_code,422)
        self.cut=second;raw=self.view()['draft_input'];raw['continuity']['previous_version_id']=str(uuid4())
        self.assertEqual(self.client.put(f'/api/cuts/{second}/draft',json=self.command(input=raw)).status_code,422)
        project=self.client.get('/api/projects').json()[0]
        scene=self.client.post(f"/api/projects/{project['id']}/scenes",json=dict(command_id=str(uuid4()),expected_revision=project['revision'],name='Altra')).json()
        self.cut=scene['cuts'][0]['id'];raw=self.view()['draft_input'];raw['continuity']=dict(mode='latent',declared_state='Stanza vuota.',previous_cut_id=first)
        self.assertEqual(self.client.put(f'/api/cuts/{self.cut}/draft',json=self.command(input=raw)).status_code,422)

    def test_video_audio_is_detected_but_never_inherited_as_audio_reference(self):
        response=self.client.post('/api/video-media',content=video_bytes(3,True))
        self.assertEqual(response.status_code,201,response.text);media=response.json();self.assertTrue(media['has_audio'])
        id=self.video(media);raw=self.view()['draft_input']
        raw['continuity']=dict(mode='video_reference',declared_state='Una stanza vuota.',video_id=id)
        raw['videos'][0].update(confirmed=True,linked_to_h3=True);self.save(raw)
        job,_=self.compile();self.assertNotIn('<Audio',job['result']['prompt'])
        self.assertEqual(self.view()['draft_input'].get('audio_references',[]),[])

    def test_video_snapshot_integrity_is_checked_before_confirmation(self):
        media=self.media();id=self.video(media);raw=self.view()['draft_input']
        raw['continuity']=dict(mode='video_reference',declared_state='Una stanza vuota.',video_id=id)
        raw['videos'][0].update(confirmed=True,linked_to_h3=True);self.save(raw)
        job,_=self.compile();version=self.view()['versions'][-1]
        self.assertEqual(version['media_snapshot']['video:'+id]['sha256'],media['sha256'])
        with closing(self.app.state.repository.connect()) as db:relative=db.execute('SELECT relative_path FROM video_media WHERE id=?',(media['id'],)).fetchone()[0]
        (Path(self.temp.name)/relative).write_bytes(b'changed')
        response=self.client.post(f'/api/cuts/{self.cut}/confirm',json=self.command(version_id=job['candidate_id']))
        self.assertEqual(response.status_code,422);self.assertEqual(response.json()['detail']['code'],'confirmation_blocked')

    def test_changing_video_slot_requires_explicit_snapshot_reconciliation(self):
        id=self.video();raw=self.view()['draft_input'];raw['continuity']=dict(mode='video_reference',declared_state='Una stanza vuota.',video_id=id)
        raw['videos'][0].update(duration_s=4.0,file_exists=True,linked_to_h3=True,confirmed=True);self.save(raw)
        job,_=self.compile();old=self.view()['versions'][-1]['text']
        raw=self.view()['draft_input'];raw['videos'][0]['slot']=2;self.save(raw)
        response=self.client.post(f'/api/cuts/{self.cut}/confirm',json=self.command(version_id=job['candidate_id']))
        self.assertEqual(response.status_code,409);self.assertEqual(response.json()['detail']['code'],'reference_reconciliation_required')
        response=self.client.post(f'/api/cuts/{self.cut}/confirm',json=self.command(version_id=job['candidate_id'],acknowledge_reference_changes=True))
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['versions'][-1]['text'],old);self.assertEqual(response.json()['draft_input']['videos'][0]['slot'],2)

    def test_result_can_be_attached_after_finalization_without_unlocking_prompt(self):
        job,_=self.compile();self.client.post(f'/api/cuts/{self.cut}/confirm',json=self.command(version_id=job['candidate_id']))
        scene=self.client.get('/api/projects').json()[0]['scenes'][0]
        finalized=self.client.put(f"/api/scenes/{scene['id']}/finalize",json=dict(command_id=str(uuid4()),expected_revision=scene['revision'],finalized=True))
        self.assertEqual(finalized.status_code,200,finalized.text);media=self.media()
        attached=self.client.put(f'/api/cuts/{self.cut}/output',json=self.command(media_id=media['id'],version_id=job['candidate_id']))
        self.assertEqual(attached.status_code,200,attached.text)
        self.assertTrue(self.client.get('/api/projects').json()[0]['scenes'][0]['finalized'])
        self.assertEqual(self.client.put(f'/api/cuts/{self.cut}/draft',json=self.command(input=self.view()['draft_input'])).status_code,409)

    def test_unknown_historical_snapshot_is_not_reconstructed_from_catalogue(self):
        self.client.post(f'/api/cuts/{self.cut}/items',json=self.command(kind='unit'));self.save(context_input())
        plan=CurrentInterpretation(narrative_en='<Subject 1> stands.',summary_en='<Subject 1> stands.',estimated_duration_s=5.0,question=None)
        job,_=self.compile(plan);previous=self.cut
        with closing(self.app.state.repository.connect()) as db:
            raw=json.loads(db.execute('SELECT data FROM versions WHERE id=?',(job['candidate_id'],)).fetchone()[0]);raw['input_snapshot']=None
            db.execute('UPDATE versions SET data=? WHERE id=?',(json.dumps(raw),job['candidate_id']))
        current=self.next_cut();self.assertFalse(current['previous_cut']['snapshot_known']);self.assertEqual(current['previous_cut']['units'],[])
        raw=self.view()['draft_input'];raw['continuity']=dict(mode='latent',declared_state='Stanza.',previous_cut_id=previous,previous_version_id=job['candidate_id']);self.save(raw)
        self.assertEqual(self.client.post(f'/api/cuts/{self.cut}/context-subject',json=self.command(subject=1)).status_code,404)

    def test_future_database_version_is_rejected_without_adding_tables(self):
        with closing(self.app.state.repository.connect()) as db:
            db.execute('DROP TABLE cut_outputs');db.execute('DROP TABLE video_media');db.execute("UPDATE settings SET value='99' WHERE key='schema_version'")
        with self.assertRaises(RuntimeError):Repository(self.temp.name)
        with closing(sqlite3.connect(Path(self.temp.name)/'workspace.sqlite3')) as db:
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='video_media'").fetchone())

    def test_subject_reuse_from_previous_snapshot_is_explicit_unconfirmed_and_photo_free(self):
        self.client.post(f'/api/cuts/{self.cut}/items',json=self.command(kind='unit'))
        raw=context_input();self.save(raw)
        plan=CurrentInterpretation(narrative_en='<Subject 1> is seated, then stands.',summary_en='<Subject 1> stands.',estimated_duration_s=5.0,question=None)
        job,_=self.compile(plan);previous=self.cut;old=self.view()['versions'][-1]
        self.next_cut();raw=self.view()['draft_input']
        raw['continuity']=dict(mode='latent',declared_state='',previous_cut_id=previous,previous_version_id=job['candidate_id'])
        self.save(raw)
        response=self.client.post(f'/api/cuts/{self.cut}/context-subject',json=self.command(subject=1))
        self.assertEqual(response.status_code,200,response.text)
        unit=response.json()['draft_input']['active_units'][0]
        self.assertFalse(unit['confirmed']);self.assertEqual(unit['sources'][0]['origin'],'context')
        self.assertEqual(response.json()['draft_input']['pictures'],[])
        self.assertEqual(response.json()['draft_input']['continuity']['declared_state'],'')
        self.assertEqual(self.client.get(f'/api/cuts/{previous}').json()['versions'][-1],old)

    def test_context_provenance_does_not_erase_canonical_picture_sources_in_project_library(self):
        for kind in ['picture','unit']:self.client.post(f'/api/cuts/{self.cut}/items',json=self.command(kind=kind))
        raw=self.view()['draft_input'];picture=raw['pictures'][0];picture.update(name='Identity',description_en='a woman',confirmed=True,linked_to_h3=True)
        raw['active_units'][0].update(name='Ann',description_en='Ann',confirmed=True,sources=[dict(picture_id=picture['id'],attribute='identity')])
        raw['request']='<Subject 1> cammina.';self.save(raw)
        plan=CurrentInterpretation(narrative_en='<Subject 1> walks.',summary_en='<Subject 1> walks.',estimated_duration_s=5.0,question=None)
        job,_=self.compile(plan);previous=self.cut
        with closing(self.app.state.repository.connect()) as db:before=tuple(db.execute('SELECT data,revision FROM project_units WHERE subject=1').fetchone())
        self.next_cut();raw=self.view()['draft_input'];raw['continuity']=dict(mode='latent',declared_state='<Subject 1> è in piedi.',previous_cut_id=previous,previous_version_id=job['candidate_id']);self.save(raw)
        reused=self.client.post(f'/api/cuts/{self.cut}/context-subject',json=self.command(subject=1))
        self.assertEqual(reused.status_code,200,reused.text);self.assertEqual(reused.json()['draft_input']['active_units'][0]['sources'][0]['origin'],'context')
        with closing(self.app.state.repository.connect()) as db:after=tuple(db.execute('SELECT data,revision FROM project_units WHERE subject=1').fetchone())
        self.assertEqual(after,before)

    def test_m3_schema_backup_and_receipt_compatibility(self):
        job,command=self.compile();repo=self.app.state.repository
        value={'operation':'compile','cut_id':self.cut,'command':WebCompileCommand.model_validate_json(json.dumps(command)).model_dump(mode='json')}
        value['command']['input'].pop('videos')
        for field in list(value['command']['input']['continuity']):
            if field not in {'mode','declared_state'}:value['command']['input']['continuity'].pop(field)
        with closing(repo.connect()) as db:
            db.execute('UPDATE commands SET payload_hash=? WHERE id=?',(digest(value),command['command_id']))
            db.execute("UPDATE settings SET value='3' WHERE key='schema_version'")
        repeated=self.client.post(f'/api/cuts/{self.cut}/compile',json=command)
        self.assertEqual(repeated.status_code,202,repeated.text);self.assertEqual(repeated.json()['id'],job['id']);self.assertEqual(self.fake.calls,1)
        before=self.view()['versions'];upgraded=Repository(self.temp.name)
        self.assertEqual(upgraded.workspace().model_dump(mode='json')['versions'],before)
        with closing(sqlite3.connect(Path(self.temp.name)/'workspace.before-m4.sqlite3')) as db:
            self.assertEqual(db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()[0],'3')


if __name__=='__main__':unittest.main()
