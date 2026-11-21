"""Collaudo locale M4 su dichiarazioni e video sintetici, una inferenza per cut."""
import argparse
import io
import json
import tempfile
import re
from pathlib import Path
from uuid import UUID, uuid4

import av
from PIL import Image, ImageDraw

from app.contracts import AddItemCommand, AttachMediaCommand, DraftCommand, WebCompileCommand
from app.domain import CompileInput
from app.interpreter import DEFAULT_TEXT_MODEL, OllamaClient, SYSTEM_PROMPT
from app.jobs import JobWorker
from app.repository import Repository
from app.video import VideoStore
import hashlib


def synthetic_video():
    output=io.BytesIO()
    with av.open(output,'w',format='mp4') as file:
        stream=file.add_stream('libx264',rate=24);stream.width=320;stream.height=180;stream.pix_fmt='yuv420p'
        for n in range(144):
            picture=Image.new('RGB',(320,180),'white');draw=ImageDraw.Draw(picture)
            draw.rectangle((n,60,n+50,120),fill=(30,90,180))
            for packet in stream.encode(av.VideoFrame.from_image(picture)):file.mux(packet)
        for packet in stream.encode():file.mux(packet)
    return output.getvalue()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--model',default=DEFAULT_TEXT_MODEL)
    parser.add_argument('--output',type=Path,default=Path('benchmark-runs/m4-real.json'));args=parser.parse_args()
    report={'model':args.model,'system_prompt_sha256':hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
            'note':'Fixture sintetiche; nessuna analisi semantica del video o generazione H3. Stato dichiarato esplicitamente.', 'runs':[]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        repo=Repository(directory);cut=repo.workspace()
        cut=repo.add_item(cut.id,AddItemCommand(command_id=uuid4(),expected_revision=cut.revision,kind='unit'))
        cut=repo.add_item(cut.id,AddItemCommand(command_id=uuid4(),expected_revision=cut.revision,kind='video'))
        media=VideoStore(repo).upload(synthetic_video(),'m4-synthetic.mp4');report['video_metadata']=media
        video_id=cut.draft_input['videos'][0]['id']
        cut=repo.attach_video(cut.id,video_id,AttachMediaCommand(command_id=uuid4(),expected_revision=cut.revision,media_id=UUID(media['id'])))
        worker=JobWorker(repo,OllamaClient())
        try:
            for case in ['latent','tail_frames','video_reference','latent_dialogue_entry']:
                mode='latent' if case=='latent_dialogue_entry' else case
                if case=='latent_dialogue_entry':
                    cut=repo.workspace()
                    for kind in ['unit','dialogue']:
                        cut=repo.add_item(cut.id,AddItemCommand(command_id=uuid4(),expected_revision=cut.revision,kind=kind))
                cut=repo.workspace();raw=cut.draft_input
                raw.update(request='<Subject 1> si alza, poi cammina fino alla porta.',pictures=[],active_units=[dict(subject=1,name='Ann',role='character',description_en='Ann',confirmed=True,sources=[dict(origin='context',attribute='identity')])])
                raw['videos'][0].update(confirmed=True,linked_to_h3=True)
                raw['continuity']=dict(mode=mode,declared_state='<Subject 1> è seduta sul divano.',external_source='Contesto sintetico esterno',seamless=True)
                if case=='latent_dialogue_entry':
                    raw['active_units'].append(dict(subject=2,name='Beth',role='character',description_en='Beth',confirmed=True,sources=[dict(origin='context',attribute='identity')]))
                    raw['request']='<Subject 1> pronuncia la battuta d1. Durante la battuta, <Subject 2> entra e si ferma accanto a lei.'
                    raw['dialogues'][0].update(text='Sono pronta.',language='Italian',speaker_subject=1,confirmed=True)
                if mode=='video_reference':raw['continuity']['video_id']=video_id
                else:
                    raw['continuity'].update(window_frames=39,trim_frames=7,sampling_prefix_frames=13)
                    if mode=='tail_frames':raw['continuity'].update(context_media_id=media['id'],context_media_kind='video')
                cut=repo.save_draft(cut.id,DraftCommand(command_id=uuid4(),expected_revision=cut.revision,input=raw))
                job,created=repo.compile(cut.id,WebCompileCommand(command_id=uuid4(),expected_revision=cut.revision,cut_id=cut.id,input=CompileInput.model_validate(raw),model=args.model))
                assert created;worker.submit(job.id);worker.pending.join()
                job=repo.job(job.id);view=repo.workspace();version=next((v for v in view.versions if v.id==job.candidate_id),None)
                report['runs'].append({'case':case,'mode':mode,'result':job.result.model_dump(mode='json'),
                    'input_snapshot':version.input_snapshot if version else None,'media_snapshot':version.media_snapshot if version else None})
                args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
                assert job.result.status=='proposal',job.result.error_code
                assert job.result.metrics.inference_calls==1
                assert '<Picture' not in job.result.prompt
                narrative=job.result.interpretation.narrative_en.lower()
                assert re.search(r'sofa|couch',narrative) and re.search(r'sitting|seated|sits',narrative), 'Stato iniziale concreto omesso'
                if mode!='video_reference':assert '<Video' not in job.result.prompt
                else:
                    assert '<Video 1>' not in job.result.interpretation.narrative_en
                    assert 'The video continues from <Video 1>.' in job.result.prompt.split('detailed_description:')[1]
                    assert '<Video 1>' in job.result.interpretation.summary_en
                if case=='latent_dialogue_entry':assert job.result.prompt.count('<d>[Italian] Sono pronta.</d>.')==1
                else:assert not re.search(r'line ends|speaks|says|dialogue',narrative), 'Parlato non richiesto'
                print(json.dumps({'case':case,'mode':mode,'status':job.result.status,'summary':job.result.interpretation.summary_en,
                    'narrative':job.result.interpretation.narrative_en,'wall_s':job.result.metrics.wall_s,'calls':job.result.metrics.inference_calls}),flush=True)
        finally:worker.close()


if __name__=='__main__':main()
