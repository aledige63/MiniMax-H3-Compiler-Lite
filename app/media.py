"""Immagini gestite: verifica del contenuto, hash e percorsi relativi."""
from contextlib import closing
import hashlib
import io
import os
import warnings
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from app.repository import now
from app.store import StoreError

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_PIXELS = 40_000_000
FORMATS = {'JPEG': ('image/jpeg', '.jpg'), 'PNG': ('image/png', '.png'), 'WEBP': ('image/webp', '.webp')}


class MediaStore:
    def __init__(self, repository):
        self.repository = repository
        self.root = repository.directory
        (self.root / 'media').mkdir(exist_ok=True, mode=0o700)

    def upload(self, content, display_name):
        if not content or len(content) > MAX_UPLOAD_BYTES:
            raise StoreError('invalid_media', 'Scegli un’immagine fino a 25 MiB.', 422)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(content)) as image:
                    format = image.format
                    width, height = image.size
                    if format not in FORMATS or width * height > MAX_PIXELS or getattr(image, 'n_frames', 1) != 1:
                        raise ValueError('unsupported')
                    image.verify()
                # verify controlla la struttura; load verifica la decodifica reale.
                with Image.open(io.BytesIO(content)) as image:
                    image.load()
        except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombWarning, Image.DecompressionBombError):
            raise StoreError('invalid_media', 'Immagine non leggibile. Usa JPEG, PNG o WebP statici, fino a 40 megapixel.', 422) from None
        sha = hashlib.sha256(content).hexdigest()
        mime, extension = FORMATS[format]
        relative = f'media/{sha}{extension}'
        # Un file può essere condiviso; nessuna cancellazione in M2.
        with self.repository.transaction() as db:
            existing = db.execute('SELECT * FROM media WHERE relative_path=?', (relative,)).fetchone()
            if existing:
                path = self.root / relative
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                    raise StoreError('media_unavailable', 'Il file gestito non è integro. Conserva l’archivio e ripristina il media.', 409)
                return self.repository.media_view(existing)
            path = self.root / relative
            if path.exists():
                if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                    raise StoreError('media_unavailable', 'Il file gestito non è integro.', 409)
            else:
                with path.open('xb') as file:
                    os.chmod(path, 0o600)
                    file.write(content); file.flush(); os.fsync(file.fileno())
            # Il nome visibile non diventa mai un percorso server/client.
            name = display_name.replace('\\', '/').split('/')[-1]
            name = ''.join(c for c in name if c.isprintable())[:160] or 'Immagine'
            id = str(uuid4())
            db.execute('INSERT INTO media VALUES (?,?,?,?,?,?,?,?,?)',
                       (id, sha, relative, mime, len(content), width, height, name, now()))
            return self.repository.media_view(db.execute('SELECT * FROM media WHERE id=?', (id,)).fetchone())

    def file(self, media_id):
        with closing(self.repository.connect()) as db:
            row = db.execute('SELECT * FROM media WHERE id=?', (str(media_id),)).fetchone()
            if not row:
                raise StoreError('not_found', 'Media non trovato.', 404)
            path = (self.root / row['relative_path']).resolve()
            if not path.is_relative_to((self.root / 'media').resolve()) or not path.is_file():
                raise StoreError('media_unavailable', 'Media non disponibile nell’archivio gestito.', 404)
            return path, row['content_type']


MAX_AUDIO_BYTES = 100 * 1024 * 1024


class AudioStore:
    def __init__(self, repository):
        self.repository = repository
        self.root = repository.directory
        (self.root / 'audio').mkdir(exist_ok=True, mode=0o700)

    @staticmethod
    def view(row):
        return {k: row[k] for k in ('id', 'sha256', 'content_type', 'byte_size', 'sample_rate', 'sample_count', 'channels', 'duration_s', 'display_name', 'created_at')}

    def _decode_aac(self, content, destination):
        # Alcuni generatori consegnano AAC ADTS con estensione .mp3. Il nome
        # non identifica il codec e libsndfile può scambiarlo per MPEG Layer II.
        if not content.startswith((b'\xff\xf0', b'\xff\xf1', b'\xff\xf8', b'\xff\xf9')):
            return False
        import av
        import soundfile as sf
        import time
        try:
            container = av.open(io.BytesIO(content), format='aac')
        except av.FFmpegError:
            return False
        with container:
            if container.format.name != 'aac':
                return False
            stream = container.streams.audio[0]
            rate, channels = stream.codec_context.sample_rate, stream.codec_context.channels
            if not 8000 <= rate <= 384000 or not 1 <= channels <= 8:
                raise ValueError('format')
            resampler = av.AudioResampler(format='fltp', layout=stream.codec_context.layout, rate=rate)
            count = 0
            deadline = time.monotonic() + 30
            try:
                with sf.SoundFile(destination, 'w', samplerate=rate, channels=channels, format='WAV', subtype='PCM_16') as output:
                    for frame in container.decode(stream):
                        for converted in resampler.resample(frame):
                            count += converted.samples
                            if count > rate * 900 or time.monotonic() > deadline:
                                raise ValueError('too_long')
                            output.write(converted.to_ndarray().T)
                    for converted in resampler.resample(None):
                        count += converted.samples
                        if count > rate * 900:
                            raise ValueError('too_long')
                        output.write(converted.to_ndarray().T)
                if not count:
                    raise ValueError('empty')
            except av.FFmpegError:
                raise ValueError('decode') from None
        return True

    def upload(self, content, display_name):
        import soundfile as sf
        import tempfile
        import subprocess
        if not content or len(content) > MAX_AUDIO_BYTES:
            raise StoreError('invalid_media', 'Scegli un WAV o MP3 fino a 100 MiB.', 422)
        sha = hashlib.sha256(content).hexdigest()
        with closing(self.repository.connect()) as db:
            old = db.execute('SELECT * FROM audio_media WHERE sha256=?', (sha,)).fetchone()
            if old:
                self.file(old['id'], verify=True)
                return self.view(old)
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            decoded = Path(temporary) / 'decoded.wav'
            try:
                try:
                    native = Path(temporary) / 'aac.wav'
                    if self._decode_aac(content, native):
                        source = sf.SoundFile(native)
                        mime = 'audio/aac'
                    else:
                        source = sf.SoundFile(io.BytesIO(content))
                        format = source.format
                        if format not in {'WAV', 'WAVEX', 'RF64', 'MP3'}:
                            source.close(); raise ValueError('format')
                        mime = 'audio/mpeg' if format == 'MP3' else 'audio/wav'
                except sf.LibsndfileError:
                    # Fallback nativo del Mac, solo dopo riconoscimento WAV/MP3.
                    wave_header = content[:4] in {b'RIFF', b'RF64'} and content[8:12] == b'WAVE'
                    mp3_header = content.startswith(b'ID3') or (len(content) > 2 and content[0] == 255 and content[1] & 224 == 224)
                    if not (wave_header or mp3_header) or not Path('/usr/bin/afconvert').is_file():
                        raise ValueError('decode') from None
                    original = Path(temporary) / ('input.wav' if wave_header else 'input.mp3'); original.write_bytes(content)
                    native = Path(temporary) / 'native.wav'
                    result = subprocess.run(['/usr/bin/afconvert', str(original), str(native), '-f', 'WAVE', '-d', 'LEI16'], capture_output=True, timeout=30)
                    if result.returncode:
                        raise ValueError('decode')
                    source = sf.SoundFile(native); mime = 'audio/wav' if wave_header else 'audio/mpeg'
                with source:
                    rate, channels = source.samplerate, source.channels
                    if not 8000 <= rate <= 384000 or not 1 <= channels <= 8:
                        raise ValueError('format')
                    count = 0
                    with sf.SoundFile(decoded, 'w', samplerate=rate, channels=channels, format='WAV', subtype='PCM_16') as preview:
                        while True:
                            block = source.read(65536, dtype='float32', always_2d=True)
                            if not len(block): break
                            count += len(block)
                            if count > rate * 900: raise ValueError('too_long')
                            preview.write(block)
                    if not count: raise ValueError('empty')
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
                raise StoreError('invalid_media', 'Audio non leggibile: usa un WAV o MP3 valido, massimo 15 minuti. Durata e formato vengono verificati dai campioni.', 422) from None
            relative = f'audio/{sha}' + {'audio/mpeg': '.mp3', 'audio/wav': '.wav', 'audio/aac': '.aac'}[mime]
            preview_path = f'audio/{sha}.preview.wav'
            with self.repository.transaction() as db:
                old = db.execute('SELECT * FROM audio_media WHERE sha256=?', (sha,)).fetchone()
                if old: return self.view(old)
                for path, data in [(self.root / relative, content), (self.root / preview_path, decoded.read_bytes())]:
                    if path.exists() and path.read_bytes() != data:
                        raise StoreError('media_unavailable', 'Un file gestito non è integro.', 409)
                    if not path.exists():
                        with path.open('xb') as file:
                            os.chmod(path, 0o600); file.write(data); file.flush(); os.fsync(file.fileno())
                name = ''.join(c for c in display_name.replace('\\', '/').split('/')[-1] if c.isprintable())[:160] or 'Audio'
                id = str(uuid4())
                db.execute('INSERT INTO audio_media VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (id, sha, relative, preview_path, mime, len(content), rate, count, channels, count / rate, name, now(), hashlib.sha256(decoded.read_bytes()).hexdigest()))
                return self.view(db.execute('SELECT * FROM audio_media WHERE id=?', (id,)).fetchone())

    def file(self, id, *, preview=False, verify=False):
        with closing(self.repository.connect()) as db:
            row = db.execute('SELECT * FROM audio_media WHERE id=?', (str(id),)).fetchone()
            if row is None: raise StoreError('not_found', 'Audio non trovato.', 404)
            path = (self.root / row['preview_path' if preview else 'relative_path']).resolve()
            if not path.is_relative_to((self.root / 'audio').resolve()) or not path.is_file():
                raise StoreError('media_unavailable', 'Audio non disponibile nell’archivio.', 404)
            expected = row['preview_sha256'] if preview else row['sha256']
            if verify and hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise StoreError('media_unavailable', 'Il file audio è cambiato fuori dall’applicazione.', 409)
            return path, 'audio/wav' if preview else row['content_type']
