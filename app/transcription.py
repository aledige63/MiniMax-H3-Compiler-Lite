"""ASR opzionale: nessuna importazione MLX o rete all'avvio del percorso testo."""
import importlib.util
import json
import time
from pathlib import Path

from app.contracts import AssistanceResult
from app.domain import Metrics
from app.interpreter import INFERENCE_LOCK
from app.store import StoreError


def configuration(directory):
    path = Path(directory) / 'asr.json'
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding='utf-8'))
    model = Path(data.get('model_dir', ''))
    if not model.is_absolute() or not (model / 'config.json').is_file() or not any((model / name).is_file() for name in ['weights.npz', 'weights.safetensors']):
        return None
    return model


def status(directory):
    available = importlib.util.find_spec('mlx_whisper') is not None and importlib.util.find_spec('scipy') is not None
    model = configuration(directory)
    return {'available': bool(available and model), 'package_installed': available, 'model_configured': model is not None,
            'model': 'local-whisper' if model else None,
            'message': 'Trascrizione automatica locale pronta. Scegli il ruolo Parlato e premi «Trascrivi audio».' if available and model else 'Trascrizione automatica non configurata. Puoi inserire e confermare manualmente il testo del parlato.'}


def transcribe(directory, audio_store, work, fingerprint):
    if not status(directory)['available']:
        raise StoreError('asr_unavailable', status(directory)['message'], 409)
    started = time.perf_counter()
    metrics = dict(model='local-whisper', digest=work['digest'], task='audio_asr', input_hash=fingerprint,
                   input_chars=0, inference_calls=0, queue_s=0.0, wall_s=0.0)
    try:
        waiting = time.perf_counter()
        with INFERENCE_LOCK:
            metrics['queue_s'] = time.perf_counter() - waiting
            # Lazy import: questi pacchetti non sono richiesti per testo/vision.
            import math
            import numpy as np
            import soundfile as sf
            from scipy.signal import resample_poly
            import mlx_whisper
            audio_store.file(work['media_id'], verify=True)
            path, _ = audio_store.file(work['media_id'], preview=True, verify=True)
            with sf.SoundFile(path) as file:
                rate = file.samplerate
                start = round(work['segment_start_s'] * rate); end = round(work['segment_end_s'] * rate)
                file.seek(start); samples = file.read(end - start, dtype='float32', always_2d=True).mean(axis=1)
            if rate != 16000:
                common = math.gcd(rate, 16000)
                samples = resample_poly(samples, 16000 // common, rate // common).astype(np.float32)
            languages = {'Italian': 'it', 'English': 'en', 'French': 'fr', 'German': 'de', 'Spanish': 'es'}
            language = languages.get(work['language'])
            metrics['inference_calls'] = 1
            result = mlx_whisper.transcribe(samples, path_or_hf_repo=str(configuration(directory)), language=language,
                                           word_timestamps=False, verbose=False, fp16=True)
        text = result.get('text')
        if not isinstance(text, str) or not text.strip() or len(text) > 20000:
            raise StoreError('asr_failed', 'Trascrizione non disponibile; inserisci il parlato manualmente.', 422)
        proposal = AssistanceResult(status='proposal', text=text.strip(), language=work['language'])
    except Exception:
        metrics['error_code'] = 'asr_failed'
        proposal = AssistanceResult(status='error', issues=['Trascrizione non disponibile. Il testo manuale resta conservato; puoi correggerlo o riprovare esplicitamente.'])
    metrics['wall_s'] = time.perf_counter() - started
    return proposal.model_copy(update={'metrics': Metrics(**metrics)})
