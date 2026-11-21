"""Job vision/traduzione/ASR, cache per contenuto e proposte da applicare esplicitamente."""
import copy
import hashlib
import json
import time
from contextlib import closing
from uuid import uuid4
from pydantic import ValidationError

from app.analysis import (ANALYSIS_VERSION, CHARACTER_SHEET_ROLES, CHARACTER_SHEET_VERSION,
                          IMAGE_ANALYSIS_TASKS, ROLE_INSTRUCTIONS, TRANSLATION_VERSION, infer, installed_model)
from app.contracts import AssistanceResult
from app.domain import ImageAnalysisSettings, Metrics
from app.image_profiles import normalized_settings, resolved_analysis
from app.interpreter import DEFAULT_TEXT_MODEL, OllamaError
from app.store import StoreError, digest
from app import transcription


def encode(data): return json.dumps(data, ensure_ascii=False, allow_nan=False)


def target_context(state, kind, target_id):
    if kind == 'vision_trial': return None
    if kind == 'audio_asr':
        audio = next((a for a in state['draft_input'].get('audio_references', []) if a['id'] == target_id), None)
        return {'audio': audio, 'epoch': state.get('audio_epochs', {}).get(target_id, 0)} if audio else None
    picture = next((p for p in state['draft_input'].get('pictures', []) if p['id'] == target_id), None)
    if not picture: return None
    # I default additivi introdotti dal DTO durante una compilazione non sono
    # correzioni del riferimento e non rendono obsoleta un'analisi in attesa.
    picture = {'description_language': 'English', 'use_original_language': False,
               'original_description': None, 'original_language': None, 'guidance': None, **picture}
    picture = dict(picture)
    settings = normalized_settings(picture.get('analysis'))
    if settings is None: picture.pop('analysis', None)
    else: picture['analysis'] = settings
    final_media = state.get('media_bindings', {}).get(target_id)
    media = final_media if kind == 'image_character_sheet' else state.get('proxy_bindings', {}).get(target_id) or final_media
    return {'picture': picture, 'media': media, 'final_media': final_media,
            'reference_revision': state.get('reference_revisions', {}).get(target_id)}


def public_job(job, state):
    value = {k: v for k, v in job.items() if k not in {'work', 'base', 'cache_key', 'force'}}
    value['stale'] = job['kind'] != 'vision_trial' and target_context(state, job['kind'], job['target_id']) != job['base']
    if job['kind'] in IMAGE_ANALYSIS_TASKS:
        value['analysis'] = job['work'].get('analysis')
    return value


class Assistance:
    def __init__(self, repository, client, media_store, audio_store):
        self.repository, self.client = repository, client
        self.media_store, self.audio_store = media_store, audio_store
        with repository.transaction() as db:
            for row in db.execute('SELECT id,data FROM assistance_jobs').fetchall():
                job = json.loads(row['data'])
                if job['status'] in {'queued', 'running'}:
                    job['status'] = 'failed'
                    job['result'] = AssistanceResult(status='error', issues=['Operazione interrotta dal riavvio: avviala nuovamente se necessaria.']).model_dump(mode='json')
                    db.execute('UPDATE assistance_jobs SET data=? WHERE id=?', (encode(job), job['id']))

    def models(self):
        with closing(self.repository.connect()) as db:
            tested = {row['digest'] for row in db.execute('SELECT digest FROM vision_trials')}
        result = []
        for model in self.client.models():
            try:
                info = model if 'capabilities' in model else self.client._request('/api/show', {'model': model['name']})
                capabilities = info.get('capabilities', [])
            except (OllamaError, AttributeError): capabilities = []
            result.append({**model, 'name': model['name'], 'digest': model['digest'], 'capabilities': capabilities,
                           'vision_tested': model['digest'] in tested})
        return result

    def settings(self):
        with closing(self.repository.connect()) as db:
            row = db.execute("SELECT value FROM settings WHERE key='models'").fetchone()
        return json.loads(row[0]) if row else {'revision': 0, 'text_model': DEFAULT_TEXT_MODEL, 'vision_model': None}

    def set_settings(self, command):
        if not command.vision_model:
            raise StoreError('vision_required', 'Scegli un modello vision: è richiesto per la configurazione completa.', 422)
        try:
            installed_model(self.client, command.text_model, 'completion')
            if command.vision_model: installed_model(self.client, command.vision_model, 'vision')
        except OllamaError as exc:
            raise StoreError('model_unavailable', 'Scegli un modello installato con la capacità richiesta.', 422) from exc
        def action(db):
            row = db.execute("SELECT value FROM settings WHERE key='models'").fetchone()
            current = json.loads(row[0]) if row else {'revision': 0}
            if command.expected_revision != current['revision']:
                raise StoreError('revision_conflict', 'La selezione dei modelli è cambiata in un altro browser.', current_revision=current['revision'])
            value = {'revision': current['revision'] + 1, 'text_model': command.text_model, 'vision_model': command.vision_model}
            db.execute("INSERT INTO settings VALUES ('models',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (encode(value),))
            return value
        return self.repository._entity_command('models', 'models', command, action)

    def create(self, cut_id, command):
        created = False
        def action(db):
            nonlocal created
            state = self.repository._load(db, cut_id, active=True)
            if command.expected_revision != state['revision']:
                raise StoreError('revision_conflict', 'Salva e ricarica la bozza prima di analizzarla.', current_revision=state['revision'])
            if state['finalized']: raise StoreError('scene_finalized', 'Riapri la scena prima di analizzare i riferimenti.')
            kind = command.kind
            if kind == 'audio_asr':
                if not transcription.status(self.repository.directory)['available']:
                    raise StoreError('asr_unavailable', transcription.status(self.repository.directory)['message'], 409)
                if command.model != 'local-whisper': raise StoreError('invalid_input', 'Seleziona l’ASR locale configurato.', 422)
                model_digest = self._asr_digest()
            else:
                try: model_digest = installed_model(self.client, command.model, 'completion' if kind == 'description_translate' else 'vision')['digest']
                except OllamaError as exc: raise StoreError('model_unavailable', 'Modello non installato o privo della capacità richiesta.', 422) from exc
                if kind in IMAGE_ANALYSIS_TASKS and not db.execute('SELECT 1 FROM vision_trials WHERE digest=?', (model_digest,)).fetchone():
                    raise StoreError('vision_not_tested', 'Esegui prima «Verifica modello vision» con il modello scelto.', 422)
            base = target_context(state, kind, command.target_id)
            work = {'digest': model_digest, 'model': command.model}
            if kind == 'vision_trial':
                key = digest({'task': kind, 'digest': model_digest, 'version': ANALYSIS_VERSION})
            elif base is None: raise StoreError('not_found', 'Riferimento non trovato nel cut.', 404)
            elif kind in IMAGE_ANALYSIS_TASKS:
                media = base['media']
                role = base['picture']['role']
                if role not in ROLE_INSTRUCTIONS:
                    raise StoreError('invalid_input', 'Scegli un ruolo dell’immagine disponibile prima dell’analisi.', 422)
                try:
                    supplied = base['picture'].get('analysis')
                    settings = ImageAnalysisSettings.model_validate({} if supplied is None else supplied)
                except ValidationError:
                    raise StoreError('invalid_input', 'Controlla categoria, livello, attributo e vista dell’analisi immagine.', 422) from None
                analysis = resolved_analysis(dict(role=role, analysis=settings.model_dump()))
                if analysis['category'] == 'attribute_transfer' and not analysis['attribute'].strip():
                    raise StoreError('invalid_input', 'Specifica l’attributo da analizzare, per esempio acconciatura o colore del rossetto.', 422)
                if kind == 'image_character_sheet':
                    if role not in CHARACTER_SHEET_ROLES or analysis['category'] != 'character':
                        raise StoreError('invalid_input', 'Per il character sheet scegli Identità o Aspetto e la categoria Personaggio.', 422)
                    if not media:
                        raise StoreError('invalid_input', 'Carica il character sheet come file della Picture.', 422)
                if not media: raise StoreError('invalid_input', 'Carica un’immagine da analizzare o un proxy esplicito.', 422)
                path, _ = self.media_store.file(media['id'])
                if hashlib.sha256(path.read_bytes()).hexdigest() != media['sha256']: raise StoreError('media_unavailable', 'Immagine gestita non integra.', 409)
                work.update(media_id=media['id'], sha256=media['sha256'], role=role, analysis=analysis)
                version = CHARACTER_SHEET_VERSION if kind == 'image_character_sheet' else ANALYSIS_VERSION
                key = digest({'task': kind, 'sha256': media['sha256'], 'role': role, 'analysis': analysis, 'digest': model_digest, 'version': version})
            elif kind == 'description_translate':
                text = base['picture'].get('description_en', '')
                language = base['picture'].get('description_language', 'English')
                if not isinstance(text, str) or not text.strip() or language == 'English':
                    raise StoreError('invalid_input', 'Inserisci il testo originale e seleziona la sua lingua prima della traduzione.', 422)
                work.update(text=text, language=language)
                key = digest({'task': kind, 'text': text, 'language': language, 'digest': model_digest, 'version': TRANSLATION_VERSION})
            else:
                audio = base['audio']
                self.audio_store.file(audio.get('media_id'), verify=True)
                end = audio.get('segment_end_s') if audio.get('segment_end_s') is not None else audio.get('measured_duration_s')
                start = audio.get('segment_start_s', 0)
                if type(end) not in (int, float) or not 0 <= start < end <= audio['measured_duration_s']:
                    raise StoreError('invalid_input', 'Scegli un segmento effettivo entro il file prima di trascrivere.', 422)
                media = db.execute('SELECT sha256 FROM audio_media WHERE id=?', (audio['media_id'],)).fetchone()
                work.update(media_id=audio['media_id'], sha256=media['sha256'], segment_start_s=start, segment_end_s=end, language=audio.get('language', 'Italian'))
                key = digest({'task': kind, 'work': work, 'version': 'whisper-segment-v1'})
            job = {'id': str(uuid4()), 'cut_id': str(cut_id), 'kind': kind, 'target_id': command.target_id,
                   'status': 'queued', 'input_revision': state['revision'], 'model': command.model, 'digest': model_digest,
                   'result': None, 'base': base, 'work': work, 'cache_key': key, 'force': command.force}
            cached = db.execute('SELECT data FROM assistance_cache WHERE key=?', (key,)).fetchone() if not command.force and kind != 'vision_trial' else None
            if cached:
                job['result'] = self._cached_result(json.loads(cached[0]), kind, command.model, model_digest, key).model_dump(mode='json')
                job['status'] = 'succeeded'
            db.execute('INSERT INTO assistance_jobs VALUES (?,?,?,?)', (job['id'], str(cut_id), kind, encode(job)))
            created = job['status'] == 'queued'
            return {'id': job['id']}
        saved = self.repository._entity_command('assistance', cut_id, command, action)
        return self.job(saved['id']), created

    @staticmethod
    def _cached_result(data, kind, model, model_digest, key):
        result = AssistanceResult.model_validate(data)
        metrics = Metrics(model=model, digest=model_digest, task=kind, input_hash=key, input_chars=0,
                          inference_calls=0, queue_s=0.0, wall_s=0.0, cache_hit=True)
        return result.model_copy(update={'metrics': metrics})

    def _asr_digest(self):
        path = transcription.configuration(self.repository.directory)
        files = [path / 'config.json', *[path / name for name in ['weights.npz', 'weights.safetensors'] if (path / name).is_file()]]
        fingerprint = hashlib.sha256()
        for file in files:
            fingerprint.update(file.name.encode())
            with file.open('rb') as source:
                for block in iter(lambda: source.read(1024 * 1024), b''):
                    fingerprint.update(block)
        return fingerprint.hexdigest()

    def job(self, id):
        with closing(self.repository.connect()) as db:
            row = db.execute('SELECT * FROM assistance_jobs WHERE id=?', (str(id),)).fetchone()
            if row is None: raise StoreError('not_found', 'Operazione non trovata.', 404)
            state = self.repository._load(db, row['cut_id'], active=True)
            return public_job(json.loads(row['data']), state)

    def run(self, id, queue_s):
        with self.repository.transaction() as db:
            row = db.execute('SELECT data FROM assistance_jobs WHERE id=?', (str(id),)).fetchone()
            if row is None: return
            job = json.loads(row[0])
            if job['status'] != 'queued': return
            job['status'] = 'running'
            db.execute('UPDATE assistance_jobs SET data=? WHERE id=?', (encode(job), job['id']))
            cached = db.execute('SELECT data FROM assistance_cache WHERE key=?', (job['cache_key'],)).fetchone() if not job['force'] and job['kind'] != 'vision_trial' else None
        started = time.perf_counter(); work = job['work']
        try:
            if cached:
                result = self._cached_result(json.loads(cached[0]), job['kind'], job['model'], job['digest'], job['cache_key'])
            elif job['kind'] == 'audio_asr':
                if self._asr_digest() != job['digest']: raise StoreError('model_changed', 'Il modello ASR è cambiato; avvia una nuova richiesta.', 409)
                result = transcription.transcribe(self.repository.directory, self.audio_store, work, job['cache_key'])
            else:
                capability = 'completion' if job['kind'] == 'description_translate' else 'vision'
                if installed_model(self.client, job['model'], capability)['digest'] != job['digest']:
                    raise StoreError('model_changed', 'Il modello è cambiato; avvia una nuova richiesta.', 409)
                content = None
                if job['kind'] in IMAGE_ANALYSIS_TASKS:
                    path, _ = self.media_store.file(work['media_id']); content = path.read_bytes()
                    if hashlib.sha256(content).hexdigest() != work['sha256']: raise StoreError('media_unavailable', 'Immagine cambiata fuori dall’applicazione.', 409)
                result = infer(self.client, job['kind'], job['model'], job['digest'], job['cache_key'], content=content,
                               role=work.get('role'), text=work.get('text'), language=work.get('language'), analysis=work.get('analysis'))
        except Exception as exc:
            message = exc.message if isinstance(exc, StoreError) else 'Operazione non riuscita. Il testo manuale e i riferimenti sono conservati.'
            result = AssistanceResult(status='error', issues=[message])
        if result.metrics:
            metrics = result.metrics.model_copy(update={'queue_s': result.metrics.queue_s + queue_s,
                                                        'wall_s': result.metrics.wall_s + queue_s})
            result = result.model_copy(update={'metrics': metrics})
        else:
            result = result.model_copy(update={'metrics': Metrics(model=job['model'], digest=job['digest'], task=job['kind'],
                input_hash=job['cache_key'], input_chars=0, inference_calls=0, queue_s=queue_s, wall_s=time.perf_counter()-started+queue_s, error_code='assistance_failed')})
        with self.repository.transaction() as db:
            current = json.loads(db.execute('SELECT data FROM assistance_jobs WHERE id=?', (job['id'],)).fetchone()[0])
            if current['status'] != 'running': return
            current['status'] = 'succeeded' if result.status == 'proposal' else 'failed'
            current['result'] = result.model_dump(mode='json')
            db.execute('UPDATE assistance_jobs SET data=? WHERE id=?', (encode(current), job['id']))
            if result.status == 'proposal':
                if job['kind'] == 'vision_trial':
                    db.execute('INSERT INTO vision_trials VALUES (?,?,?) ON CONFLICT(digest) DO UPDATE SET data=excluded.data', (job['digest'], job['model'], encode(current)))
                else: db.execute('INSERT INTO assistance_cache VALUES (?,?) ON CONFLICT(key) DO UPDATE SET data=excluded.data', (job['cache_key'], result.model_dump_json()))

    def apply(self, cut_id, id, command):
        def action(state):
            db = self.repository._transaction_db
            row = db.execute('SELECT data FROM assistance_jobs WHERE id=? AND cut_id=?', (str(id), str(cut_id))).fetchone()
            if row is None: raise StoreError('not_found', 'Proposta non trovata in questo cut.', 404)
            job = json.loads(row[0])
            if job['kind'] == 'vision_trial' or job['status'] != 'succeeded' or not job['result'].get('text'):
                raise StoreError('invalid_input', 'Nessuna proposta applicabile.', 422)
            if target_context(state, job['kind'], job['target_id']) != job['base']:
                raise StoreError('stale_analysis', 'Il riferimento è cambiato dopo la richiesta. Il testo più recente è conservato; puoi leggere la proposta o avviare una nuova analisi.')
            if job['kind'] == 'audio_asr':
                audio = next(a for a in state['draft_input']['audio_references'] if a['id'] == job['target_id'])
                audio.update(transcript=job['result']['text'], confirmed=False)
            else:
                picture = next(p for p in state['draft_input']['pictures'] if p['id'] == job['target_id'])
                if job['kind'] == 'description_translate':
                    picture.update(original_description=job['work']['text'], original_language=job['work']['language'])
                picture.update(description_en=job['result']['text'], description_language='English', use_original_language=False, confirmed=False)
            state['state'] = 'draft'
        return self.repository._command(f'apply_assistance:{id}', cut_id, command, action)[0]

    def attach_proxy(self, cut_id, picture_id, command):
        def action(state):
            db = self.repository._transaction_db
            if not any(p['id'] == str(picture_id) for p in state['draft_input'].get('pictures', [])):
                raise StoreError('not_found', 'Picture non presente nel cut.', 404)
            row = db.execute('SELECT id,sha256 FROM media WHERE id=?', (str(command.media_id),)).fetchone()
            if not row: raise StoreError('not_found', 'Immagine proxy non trovata.', 404)
            state.setdefault('proxy_bindings', {})[str(picture_id)] = dict(row)
            db.execute('INSERT INTO reference_proxies VALUES (?,?) ON CONFLICT(reference_id) DO UPDATE SET media_id=excluded.media_id', (str(picture_id), str(command.media_id)))
            state['state'] = 'draft'
        return self.repository._command(f'proxy:{picture_id}', cut_id, command, action)[0]

    def clear_proxy(self, cut_id, picture_id, command):
        def action(state):
            state.setdefault('proxy_bindings', {}).pop(str(picture_id), None)
            self.repository._transaction_db.execute('DELETE FROM reference_proxies WHERE reference_id=?', (str(picture_id),))
            state['state'] = 'draft'
        return self.repository._command(f'clear_proxy:{picture_id}', cut_id, command, action)[0]

    def cancel(self, cut_id, id, command):
        def action(db):
            state = self.repository._load(db, cut_id, active=True)
            if command.expected_revision != state['revision']:
                raise StoreError('revision_conflict', 'La bozza è cambiata: aggiorna lo stato prima di annullare.', current_revision=state['revision'])
            row = db.execute('SELECT data FROM assistance_jobs WHERE id=? AND cut_id=?', (str(id), str(cut_id))).fetchone()
            if not row: raise StoreError('not_found', 'Operazione non trovata.', 404)
            job = json.loads(row[0])
            if job['status'] not in {'queued','running'}: raise StoreError('job_finished', 'Operazione già terminata.')
            job['status'] = 'cancelled'
            job['result'] = AssistanceResult(status='error', issues=['Operazione annullata. Un’inferenza già iniziata termina senza applicare il risultato.']).model_dump(mode='json')
            db.execute('UPDATE assistance_jobs SET data=? WHERE id=?', (encode(job), str(id)))
            return public_job(job, state)
        return self.repository._entity_command(f'cancel_assistance:{id}', cut_id, command, action)
