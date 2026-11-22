"""API locale con archivio condiviso e assistenza multimodale M3."""
from contextlib import asynccontextmanager, closing
import json
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID
from typing import Literal

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.concurrency import run_in_threadpool

from app.contracts import (AddItemCommand, AddSourceCommand, AttachMediaCommand, ConfirmVersionCommand,
                           CreateCutCommand, DraftCommand, FinalizeCommand, HealthView, ModelView, NamedCommand,
                           PasswordCommand, ReuseCommand, RevisionCommand, TrashCommand, LibraryTrashCommand, WebCompileCommand, WebManualPromptCommand,
                           AssistanceCommand, ModelSettingsCommand, AttachOutputCommand, ReuseContextCommand, ImportDialoguesCommand,
                           ExportSelection, PurgeSelection, PurgeCommand, SaveCameraPresetCommand)
from app.contracts import AccessSettingsCommand, ConnectionSettingsCommand, ConnectionTrialCommand
from app.connections import Connections
from app.access import Access, loopback
from app.media import MAX_UPLOAD_BYTES, MAX_AUDIO_BYTES, MediaStore, AudioStore
from app.assistance import Assistance
from app.video import VideoStore, MAX_VIDEO_BYTES
from app import transcription
from app.interpreter import DEFAULT_TEXT_MODEL, OllamaClient, OllamaError
from app.jobs import JobWorker
from app.repository import Repository, StoreError
from app.validation import validation_messages
from app.exporting import ExportService, text_document, print_document, filename


def create_app(data_dir=None, client=None, *, lan=False, allowed_hosts=None, connection_factory=None):
    root = Path(__file__).resolve().parent.parent
    repository = Repository(Path(data_dir) if data_dir else root / "data")
    access = Access(repository, lan=lan)
    media_store = MediaStore(repository)
    audio_store = AudioStore(repository)
    video_store = VideoStore(repository)
    connections = Connections(repository, factory=connection_factory)
    ollama = client if client is not None else connections
    assistance = Assistance(repository, ollama, media_store, audio_store)
    worker = JobWorker(repository, ollama, assistance=assistance, connections=connections)
    exports = ExportService(repository)

    @asynccontextmanager
    async def lifespan(app):
        yield
        worker.close()

    app = FastAPI(title="MiniMax H3 Compiler Lite", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.repository, app.state.worker, app.state.access = repository, worker, access
    app.state.assistance = assistance
    app.state.connections = connections
    app.state.exports = exports
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", *(allowed_hosts or [])])

    @app.middleware("http")
    async def local_origin(request, call_next):
        origin = request.headers.get("origin")
        if request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail': {'code': 'forbidden', 'message': 'Origine non consentita.'}}, status_code=403)
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin:
            parsed = urlparse(origin)
            if parsed.scheme not in {"http", "https"} or parsed.netloc != request.headers.get("host"):
                return JSONResponse({"detail": {"code": "invalid_input", "message": "Origine della richiesta non consentita."}}, status_code=403)
        if request.url.path.startswith('/api/') and request.url.path not in {'/api/access/status', '/api/access/login'}:
            try:
                access.authorize(request)
            except StoreError as exc:
                return JSONResponse({'detail': {'code': exc.code, 'message': exc.message}}, status_code=exc.status)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['X-Frame-Options'] = 'DENY'
        return response

    @app.get('/api/access/status')
    def access_status(request: Request):
        return access.status(request)

    @app.post('/api/access/login')
    async def login(request: Request, response: Response):
        command = await body(request, PasswordCommand)
        return access.login(request, command.password, response)

    @app.post('/api/access/logout')
    def logout(request: Request, response: Response):
        return access.logout(request, response)

    @app.put('/api/access/password')
    async def password(request: Request, response: Response):
        if not loopback(request):
            raise StoreError('forbidden', 'Imposta la password dal browser sul Mac centrale.', 403)
        command = await body(request, AccessSettingsCommand)
        return await run_in_threadpool(access.change, request, command, response)

    @app.put('/api/access/settings')
    async def access_settings(request: Request, response: Response):
        command = await body(request, AccessSettingsCommand)
        return await run_in_threadpool(access.change, request, command, response)

    @app.get('/api/access/bootstrap')
    def bootstrap(request: Request):
        if not loopback(request):
            raise StoreError('forbidden', 'Disponibile soltanto sul Mac centrale.', 403)
        return {'password': access.bootstrap.read_text(encoding='utf-8') if access.bootstrap.exists() else None}

    @app.exception_handler(StoreError)
    async def store_error(request, exc):
        detail = {"code": exc.code, "message": exc.message}
        if exc.current_revision is not None:
            detail["current_revision"] = exc.current_revision
        if exc.issues:
            detail["issues"] = exc.issues
        return JSONResponse({"detail": detail}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def invalid_route(request, exc):
        return JSONResponse({"detail": {"code": "invalid_input", "message": "Identificatore o parametro non valido."}}, status_code=422)

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        return JSONResponse({"detail": {"code": "internal_error", "message": "Operazione non riuscita; i dati precedenti sono conservati."}}, status_code=500)

    async def body(request, model):
        content = await request.body()
        try:
            return model.model_validate_json(content)
        except ValidationError as exc:
            try:
                raw = json.loads(content)
            except (ValueError, UnicodeDecodeError):
                raw = {}
            messages = validation_messages(exc, raw)
            incomplete = any(error["type"] == "input_incomplete" for error in exc.errors())
            raise StoreError("incomplete_input" if incomplete else "invalid_input",
                             "\n".join(messages), 422, issues=messages) from None

    @app.get("/api/health")
    def health():
        try:
            available = bool(ollama.models())
        except OllamaError:
            available = False
        return HealthView(ollama_available=available, default_model=DEFAULT_TEXT_MODEL)

    @app.get("/api/models")
    def models():
        try:
            return [ModelView(name=m["name"], digest=m["digest"]) for m in ollama.models()]
        except OllamaError:
            raise StoreError("service_unreachable", "Ollama non è raggiungibile.", 503) from None

    @app.get("/api/workspace")
    def workspace():
        return repository.workspace()

    @app.get('/api/projects')
    def projects():
        return repository.projects()

    @app.post('/api/exports')
    async def prepare_export(request: Request):
        return await run_in_threadpool(exports.prepare,await body(request,ExportSelection))

    @app.get('/api/exports/{token}/txt')
    def export_text(token: str):
        from urllib.parse import quote
        document=exports.get(token)
        return PlainTextResponse(text_document(document),headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(filename(document),safe='')})

    @app.get('/api/exports/{token}/print',response_class=HTMLResponse)
    def export_print(token: str):
        return HTMLResponse(print_document(exports.get(token)),headers={'Content-Security-Policy':"default-src 'none'; script-src 'self'; style-src 'self'; base-uri 'none'; frame-ancestors 'none'"})

    def inference_busy():
        with worker.pending.mutex:return bool(worker.pending.unfinished_tasks)

    def idle_connections():
        if inference_busy():
            raise StoreError('connections_busy', 'Attendi il termine dei lavori in coda prima di cambiare connessioni o modelli.', 409)

    @app.get('/api/connections')
    def connection_settings():
        return connections.settings()

    @app.put('/api/connections')
    async def save_connections(request: Request):
        command = await body(request, ConnectionSettingsCommand)
        def save():
            with connections.lock:
                idle_connections()
                return connections.save(command)
        return await run_in_threadpool(save)

    @app.get('/api/connections/models/{service}')
    def connection_models(service: Literal['ollama', 'openai']):
        with connections.lock:
            try:
                return connections.service_models(service)
            except OllamaError as exc:
                from app.interpreter import PUBLIC_ERRORS
                raise StoreError(exc.code, PUBLIC_ERRORS.get(exc.code, 'Connessione non disponibile.'), 503) from None

    @app.post('/api/connections/trials', status_code=202)
    async def connection_trial(request: Request):
        command = await body(request, ConnectionTrialCommand)
        def submit():
            with connections.lock:
                value = connections.create_trial(command)
                worker.submit_trial(value['id'])
                return value
        return await run_in_threadpool(submit)

    @app.get('/api/connections/trials/{id}')
    def connection_trial_result(id: UUID):
        return connections.trial(id)

    @app.post('/api/trash/preview')
    async def purge_preview(request: Request):
        result=await run_in_threadpool(repository.purge_preview,await body(request,PurgeSelection))
        if inference_busy():result['blockers'].append('Attendi il termine del lavoro locale prima di eliminare definitivamente.')
        return result

    @app.post('/api/trash/purge')
    async def purge_trash(request: Request):
        command=await body(request,PurgeCommand)
        if inference_busy():raise StoreError('purge_busy','Attendi il termine del lavoro locale prima di eliminare definitivamente.',409)
        result=await run_in_threadpool(repository.purge,command)
        exports.invalidate(result['removed_ids'])
        return result

    @app.post('/api/trash/cleanup')
    async def retry_cleanup(request: Request):
        await body(request,RevisionCommand)
        if inference_busy():raise StoreError('purge_busy','Attendi il termine del lavoro locale.',409)
        await run_in_threadpool(repository.cleanup_files)
        with closing(repository.connect()) as db:
            return {'pending_files': db.execute('SELECT count(*) FROM pending_file_deletions').fetchone()[0]}

    @app.get('/api/cuts/{cut_id}/dialogues/preview')
    def preview_dialogues(cut_id: UUID):
        return repository.preview_dialogues(cut_id)

    @app.post('/api/cuts/{cut_id}/dialogues/import')
    async def import_dialogues(cut_id: UUID, request: Request):
        return repository.import_dialogues(cut_id,await body(request,ImportDialoguesCommand))

    @app.get('/api/assistance/models')
    def assistance_models():
        return assistance.models()

    @app.get('/api/assistance/settings')
    def assistance_settings():
        return assistance.settings()

    @app.put('/api/assistance/settings')
    async def save_model_settings(request: Request):
        command = await body(request, ModelSettingsCommand)
        def save():
            with connections.lock:
                idle_connections()
                return assistance.set_settings(command)
        return await run_in_threadpool(save)

    @app.get('/api/assistance/asr')
    def asr_status():
        return transcription.status(repository.directory)

    @app.post('/api/cuts/{cut_id}/assistance', status_code=202)
    async def request_assistance(cut_id: UUID, request: Request):
        command = await body(request, AssistanceCommand)
        def submit():
            with connections.lock:
                job, created = assistance.create(cut_id, command)
                if created: worker.submit_assistance(job['id'])
                return job
        return await run_in_threadpool(submit)

    @app.get('/api/assistance/jobs/{id}')
    def assistance_job(id: UUID):
        return assistance.job(id)

    @app.post('/api/cuts/{cut_id}/assistance/{id}/dismiss')
    async def dismiss_assistance(cut_id: UUID, id: UUID, request: Request):
        return assistance.dismiss(cut_id, id, await body(request, RevisionCommand))

    @app.post('/api/cuts/{cut_id}/assistance/{id}/apply')
    async def apply_assistance(cut_id: UUID, id: UUID, request: Request):
        return assistance.apply(cut_id, id, await body(request, RevisionCommand))

    @app.post('/api/cuts/{cut_id}/assistance/{id}/cancel')
    async def cancel_assistance(cut_id: UUID, id: UUID, request: Request):
        return assistance.cancel(cut_id, id, await body(request, RevisionCommand))

    @app.put('/api/cuts/{cut_id}/pictures/{picture_id}/proxy')
    async def attach_proxy(cut_id: UUID, picture_id: UUID, request: Request):
        return assistance.attach_proxy(cut_id, picture_id, await body(request, AttachMediaCommand))

    @app.post('/api/cuts/{cut_id}/pictures/{picture_id}/proxy/reset')
    async def clear_proxy(cut_id: UUID, picture_id: UUID, request: Request):
        return assistance.clear_proxy(cut_id, picture_id, await body(request, RevisionCommand))

    @app.post('/api/projects')
    async def new_project(request: Request):
        return repository.create_project(await body(request, NamedCommand))

    @app.post('/api/projects/{project_id}/scenes')
    async def new_scene(project_id: UUID, request: Request):
        return repository.create_scene(project_id, await body(request, NamedCommand))

    @app.post('/api/scenes/{scene_id}/cuts')
    async def new_cut(scene_id: UUID, request: Request):
        return repository.create_cut(scene_id, await body(request, CreateCutCommand))

    @app.put('/api/projects/{id}/name')
    async def rename_project(id: UUID, request: Request):
        return repository.rename('projects', id, await body(request, NamedCommand))

    @app.put('/api/scenes/{id}/name')
    async def rename_scene(id: UUID, request: Request):
        return repository.rename('scenes', id, await body(request, NamedCommand))

    @app.put('/api/cuts/{id}/name')
    async def rename_cut(id: UUID, request: Request):
        return repository.rename('cuts', id, await body(request, NamedCommand))

    @app.put('/api/projects/{id}/trash')
    async def trash_project(id: UUID, request: Request):
        return repository.trash('projects', id, await body(request, TrashCommand))

    @app.put('/api/scenes/{id}/trash')
    async def trash_scene(id: UUID, request: Request):
        return repository.trash('scenes', id, await body(request, TrashCommand))

    @app.put('/api/cuts/{id}/trash')
    async def trash_cut(id: UUID, request: Request):
        return repository.trash_cut(id, await body(request, TrashCommand))

    @app.put('/api/scenes/{id}/finalize')
    async def finalize_scene(id: UUID, request: Request):
        return repository.finalize(id, await body(request, FinalizeCommand))

    @app.get('/api/projects/{project_id}/library')
    def library(project_id: UUID, scene_id: UUID | None = None):
        return repository.library(project_id,scene_id)

    @app.put('/api/projects/{project_id}/library/{kind}/{reference_id}/trash')
    async def trash_library(project_id: UUID, kind: Literal['picture','unit'], reference_id: UUID, request: Request):
        return repository.trash_library(project_id, kind, reference_id, await body(request, LibraryTrashCommand))

    @app.put('/api/projects/{project_id}/camera-presets/{tag}')
    async def save_camera_preset(project_id: UUID, tag: str, request: Request):
        return repository.save_camera_preset(project_id, tag, await body(request, SaveCameraPresetCommand))

    @app.post('/api/scenes/{scene_id}/subjects/compact')
    async def compact_subjects(scene_id: UUID, request: Request):
        if inference_busy():raise StoreError('subjects_busy','Attendi il termine del lavoro locale prima di rinumerare.',409)
        return repository.compact_scene_subjects(scene_id,await body(request,RevisionCommand))

    @app.post('/api/cuts/{cut_id}/context-subject')
    async def context_subject(cut_id: UUID, request: Request):
        return repository.reuse_context_subject(cut_id, await body(request, ReuseContextCommand))

    @app.post('/api/video-media', status_code=201)
    async def upload_video(request: Request):
        content = bytearray()
        async for block in request.stream():
            content.extend(block)
            if len(content) > MAX_VIDEO_BYTES:
                raise StoreError('invalid_media', 'Video oltre il limite di 300 MiB.', 413)
        from urllib.parse import unquote
        return await run_in_threadpool(video_store.upload, bytes(content), unquote(request.headers.get('X-File-Name', 'Video')))

    @app.get('/api/video-media/{id}')
    def video_file(id: UUID, frame: Literal['first', 'last'] | None = None):
        path, mime = video_store.file(id, frame=frame)
        return FileResponse(path, media_type=mime)

    @app.put('/api/cuts/{cut_id}/videos/{video_id}/media')
    async def attach_video(cut_id: UUID, video_id: str, request: Request):
        return repository.attach_video(cut_id, video_id, await body(request, AttachMediaCommand))

    @app.put('/api/cuts/{cut_id}/output')
    async def attach_output(cut_id: UUID, request: Request):
        return repository.attach_output(cut_id, await body(request, AttachOutputCommand))

    @app.get('/api/cuts/{cut_id}')
    def cut(cut_id: UUID):
        return repository.workspace(cut_id)

    @app.post('/api/cuts/{cut_id}/reuse')
    async def reuse(cut_id: UUID, request: Request):
        return repository.reuse(cut_id, await body(request, ReuseCommand))

    @app.post('/api/cuts/{cut_id}/confirm')
    async def confirm(cut_id: UUID, request: Request):
        return repository.confirm(cut_id, await body(request, ConfirmVersionCommand))

    @app.post('/api/media')
    async def upload(request: Request):
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > MAX_UPLOAD_BYTES:
                raise StoreError('invalid_media', 'Il file supera 25 MiB.', 413)
        from urllib.parse import unquote
        return await run_in_threadpool(media_store.upload, bytes(content), unquote(request.headers.get('x-file-name', 'Immagine')))

    @app.get('/api/media/{media_id}')
    def media_file(media_id: UUID):
        path, mime = media_store.file(media_id)
        return FileResponse(path, media_type=mime)

    @app.post('/api/audio-media')
    async def upload_audio(request: Request):
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > MAX_AUDIO_BYTES: raise StoreError('invalid_media', 'Il file supera 100 MiB.', 413)
        from urllib.parse import unquote
        return await run_in_threadpool(audio_store.upload, bytes(content), unquote(request.headers.get('x-file-name', 'Audio')))

    @app.get('/api/audio-media/{id}')
    def audio_file(id: UUID, preview: bool = True):
        path, mime = audio_store.file(id, preview=preview)
        return FileResponse(path, media_type=mime)

    @app.put('/api/cuts/{cut_id}/audio/{audio_id}/media')
    async def attach_audio(cut_id: UUID, audio_id: str, request: Request):
        return repository.attach_audio(cut_id, audio_id, await body(request, AttachMediaCommand))

    @app.put('/api/cuts/{cut_id}/pictures/{picture_id}/media')
    async def attach_media(cut_id: UUID, picture_id: UUID, request: Request):
        return repository.attach_media(cut_id, picture_id, await body(request, AttachMediaCommand))

    @app.put("/api/cuts/{cut_id}/draft")
    async def draft(cut_id: UUID, request: Request):
        return repository.save_draft(cut_id, await body(request, DraftCommand))

    @app.post("/api/cuts/{cut_id}/items")
    async def item(cut_id: UUID, request: Request):
        return repository.add_item(cut_id, await body(request, AddItemCommand))

    @app.post("/api/cuts/{cut_id}/sources")
    async def source(cut_id: UUID, request: Request):
        return repository.add_source(cut_id, await body(request, AddSourceCommand))

    @app.post("/api/cuts/{cut_id}/compile", status_code=202)
    async def compile_cut(cut_id: UUID, request: Request):
        command = await body(request, WebCompileCommand)
        def submit():
            with connections.lock:
                chosen = command.model or assistance.settings()['text_model']
                job, created = repository.compile(cut_id, command, default_model=chosen)
                if created:
                    worker.submit(job.id)
                return job
        return await run_in_threadpool(submit)

    @app.get("/api/jobs/{job_id}")
    def job(job_id: UUID):
        return repository.job(job_id)

    @app.post('/api/jobs/{job_id}/cancel')
    async def cancel(job_id: UUID, request: Request):
        return repository.cancel_job(job_id, await body(request, RevisionCommand))

    @app.put("/api/cuts/{cut_id}/manual")
    async def manual(cut_id: UUID, request: Request):
        return repository.save_manual(cut_id, await body(request, WebManualPromptCommand))

    @app.get("/api/cuts/{cut_id}/text", response_class=PlainTextResponse)
    def text(cut_id: UUID, version_id: UUID):
        return repository.text(cut_id, version_id)

    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=static_dir), name="assets")

        @app.get("/")
        def index():
            return FileResponse(static_dir / "index.html")
    return app
