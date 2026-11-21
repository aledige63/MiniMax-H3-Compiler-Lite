"""Archivio video e preview locali; nessuna analisi semantica o invio al modello."""
import hashlib
import io
import json
import os
import time
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from app.store import StoreError

MAX_VIDEO_BYTES = 300 * 1024 * 1024


class VideoStore:
    def __init__(self, repository):
        self.repository = repository
        self.root = repository.directory
        (self.root / 'video').mkdir(exist_ok=True, mode=0o700)

    @staticmethod
    def view(row):
        value = json.loads(row['data'])
        return {k: v for k, v in value.items() if k not in {'poster_path', 'tail_path', 'poster_sha256', 'tail_sha256'}} | {'id': row['id'], 'sha256': row['sha256']}

    def upload(self, content, name):
        import av
        if not content or len(content) > MAX_VIDEO_BYTES:
            raise StoreError('invalid_media', 'Scegli un video MP4/MOV o WebM fino a 300 MiB.', 422)
        sha = hashlib.sha256(content).hexdigest()
        with closing(self.repository.connect()) as db:
            old = db.execute('SELECT * FROM video_media WHERE sha256=?', (sha,)).fetchone()
            if old:
                self.file(old['id'], verify=True)
                return self.view(old)
        started = time.monotonic()
        try:
            with av.open(io.BytesIO(content), options={'protocol_whitelist': 'pipe', 'format_whitelist': 'mov,matroska,webm'}) as container:
                if not container.streams.video: raise ValueError('no_video')
                stream = container.streams.video[0]
                if stream.width * stream.height > 4096 * 2160: raise ValueError('resolution')
                format = container.format.name
                if not any(name in format.split(',') for name in ['mov', 'mp4', 'matroska', 'webm']): raise ValueError('format')
                rate = float(stream.average_rate) if stream.average_rate else None
                count, first_time, last_time, last_delta, first, last = 0, None, None, None, None, None
                variable = False
                for frame in container.decode(stream):
                    if time.monotonic() - started > 30: raise ValueError('decode_limit')
                    if frame.width * frame.height > 4096 * 2160: raise ValueError('resolution')
                    timestamp = float(frame.pts * frame.time_base) if frame.pts is not None else None
                    if timestamp is None: raise ValueError('missing_timestamps')
                    if first_time is None:
                        first_time = timestamp; first = frame.to_image()
                    if last_time is not None:
                        delta = timestamp - last_time
                        if delta <= 0: raise ValueError('timestamps')
                        if last_delta and abs(delta - last_delta) > max(.00001, last_delta * .01): variable = True
                        last_delta = delta
                    last_time = timestamp; last = frame; count += 1
                    if count > 36000 or last_time - first_time > 600: raise ValueError('too_long')
                if not count or first is None or last is None: raise ValueError('empty')
                end_duration = float(last.duration * last.time_base) if last.duration else last_delta or (1 / rate if rate else 0)
                duration = last_time - first_time + end_duration
                if duration <= 0 or duration > 600: raise ValueError('duration')
                tail = last.to_image()
                codec = stream.codec_context.name
                has_audio = bool(container.streams.audio)
                width, height = first.size
        except (av.FFmpegError, ValueError, OSError, OverflowError):
            raise StoreError('invalid_media', 'Video non leggibile o fuori limite: usa MP4/MOV o WebM, fino a 10 minuti e 4K. Il file deve avere fotogrammi e tempi decodificabili.', 422) from None
        images = []
        for picture in [first, tail]:
            picture.thumbnail((1280, 1280))
            output = io.BytesIO(); picture.save(output, 'PNG'); images.append(output.getvalue())
        webm = 'matroska' in format or 'webm' in format
        relative = f'video/{sha}' + ('.webm' if webm else '.mp4')
        poster_path, tail_path = f'video/{sha}.first.png', f'video/{sha}.last.png'
        safe_name = ''.join(c for c in name.replace('\\', '/').split('/')[-1] if c.isprintable())[:160] or 'Video'
        meta = dict(display_name=safe_name, content_type='video/webm' if webm else 'video/mp4',
                    byte_size=len(content), duration_s=duration, frame_count=count, fps=rate, variable_fps=variable,
                    width=width, height=height, codec=codec, has_audio=has_audio,
                    poster_path=poster_path, tail_path=tail_path,
                    poster_sha256=hashlib.sha256(images[0]).hexdigest(), tail_sha256=hashlib.sha256(images[1]).hexdigest())
        with self.repository.transaction() as db:
            old = db.execute('SELECT * FROM video_media WHERE sha256=?', (sha,)).fetchone()
            if old: return self.view(old)
            for path, data in [(relative, content), (poster_path, images[0]), (tail_path, images[1])]:
                target = self.root / path
                if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != hashlib.sha256(data).hexdigest():
                    raise StoreError('media_unavailable', 'Un file video gestito non è integro.', 409)
                if not target.exists():
                    with target.open('xb') as file:
                        os.chmod(target, 0o600); file.write(data); file.flush(); os.fsync(file.fileno())
            id = str(uuid4())
            db.execute('INSERT INTO video_media VALUES (?,?,?,?)', (id, sha, relative, json.dumps(meta)))
            return self.view(db.execute('SELECT * FROM video_media WHERE id=?', (id,)).fetchone())

    def file(self, id, *, frame=None, verify=False):
        with closing(self.repository.connect()) as db:
            row = db.execute('SELECT * FROM video_media WHERE id=?', (str(id),)).fetchone()
            if row is None: raise StoreError('not_found', 'Video non trovato.', 404)
            meta = json.loads(row['data'])
            relative = meta['poster_path' if frame == 'first' else 'tail_path'] if frame else row['relative_path']
            path = (self.root / relative).resolve()
            if not path.is_relative_to((self.root / 'video').resolve()) or not path.is_file():
                raise StoreError('media_unavailable', 'Video non disponibile nell’archivio gestito.', 404)
            expected = meta['poster_sha256' if frame == 'first' else 'tail_sha256'] if frame else row['sha256']
            if verify and hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise StoreError('media_unavailable', 'Il video gestito è cambiato fuori dall’applicazione.', 409)
            return path, 'image/png' if frame else meta['content_type']
