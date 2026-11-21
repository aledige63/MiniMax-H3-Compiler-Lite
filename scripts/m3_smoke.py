"""Prova reale M3 su un disegno sintetico, senza dati o media dell'utente."""
import argparse
import io
import json
import tempfile
import time
from pathlib import Path
from uuid import UUID, uuid4

from PIL import Image, ImageDraw

from app.assistance import Assistance
from app.contracts import AddItemCommand, AssistanceCommand, AttachMediaCommand, DraftCommand, RevisionCommand
from app.interpreter import OllamaClient
from app.jobs import JobWorker
from app.media import AudioStore, MediaStore
from app.repository import Repository


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', required=True)
    parser.add_argument('--output', type=Path, default=Path('benchmark-runs/m3-vision.json'))
    args = parser.parse_args()
    report = {'model': args.model, 'fixture': 'blue short-sleeved T-shirt drawing on white', 'jobs': []}
    with tempfile.TemporaryDirectory(prefix='minimax-m3-real-') as directory:
        repo = Repository(directory); media = MediaStore(repo)
        assistance = Assistance(repo, OllamaClient(timeout_s=120), media, AudioStore(repo))
        worker = JobWorker(repo, assistance.client, assistance=assistance)
        def run(kind, target=None):
            cut = repo.workspace()
            job, created = assistance.create(cut.id, AssistanceCommand(command_id=uuid4(), expected_revision=cut.revision,
                                          kind=kind, target_id=target, model=args.model))
            if created: worker.submit_assistance(job['id'])
            deadline = time.monotonic() + 180
            while job['status'] in {'queued', 'running'} and time.monotonic() < deadline:
                time.sleep(.2); job = assistance.job(job['id'])
            report['jobs'].append(job)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
            if job['status'] != 'succeeded': raise RuntimeError('Prova multimodale non riuscita; vedere il report sintetico.')
            return job
        try:
            run('vision_trial')
            cut = repo.workspace()
            cut = repo.add_item(cut.id, AddItemCommand(command_id=uuid4(), expected_revision=cut.revision, kind='picture'))
            picture = cut.draft_input['pictures'][0]; picture.update(role='outfit', name='T-shirt sintetica')
            cut = repo.save_draft(cut.id, DraftCommand(command_id=uuid4(), expected_revision=cut.revision, input=cut.draft_input))
            image = Image.new('RGB', (480, 480), 'white'); draw = ImageDraw.Draw(image)
            draw.polygon([(160,90),(210,70),(270,70),(320,90),(410,170),(350,240),(315,210),(315,410),(165,410),(165,210),(130,240),(70,170)], fill=(30,90,200))
            draw.arc((207,48,273,108), 0, 180, fill='white', width=18)
            content = io.BytesIO(); image.save(content, 'PNG')
            record = media.upload(content.getvalue(), 'blue-tshirt.png')
            cut = repo.attach_media(cut.id, picture['id'], AttachMediaCommand(command_id=uuid4(), expected_revision=cut.revision, media_id=UUID(record['id'])))
            proposal = run('image_analyze', picture['id'])
            cached = run('image_analyze', picture['id'])
            assert cached['result']['metrics']['cache_hit'] and cached['result']['metrics']['inference_calls'] == 0
            current = repo.workspace()
            raw = current.draft_input; raw['pictures'][0]['description_en'] = 'MANUAL CORRECTION PRESERVED'
            current = repo.save_draft(current.id, DraftCommand(command_id=uuid4(), expected_revision=current.revision, input=raw))
            assert assistance.job(proposal['id'])['stale']
            report['manual_correction_preserved'] = repo.workspace().draft_input['pictures'][0]['description_en'] == 'MANUAL CORRECTION PRESERVED'
            report['cache_zero_calls'] = True
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
            print(json.dumps({'vision_trial':'passed','description':proposal['result']['text'],'cache_calls':cached['result']['metrics']['inference_calls'],'manual_preserved':report['manual_correction_preserved']}))
        finally: worker.close()


if __name__ == '__main__': main()
