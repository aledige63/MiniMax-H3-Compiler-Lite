"""Archivio SQLite M2: gerarchia, versioni immutabili e comandi transazionali."""
import copy
import hashlib
import json
import os
import sqlite3
import tempfile
import threading
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.contracts import CutView, JobView, ProjectView, PromptVersion, SceneView
from app.cut_operations import CutOperations
from app.continuity import ContinuityOperations
from app.archive import ArchiveOperations
from app.subjects import SubjectOperations, draft_subject_numbers
from app.shots import ShotLibraryOperations
from app.domain import CompileInput, CompileResult
from app.dialogue_import import quoted_speech
from app.store import StoreError, digest, dto
from app.physical import unit_picture_ids, detail_content
from app.scale import canonical_scale, resolve_scale_subject
from app.image_profiles import normalized_settings
from app.library import LibraryOperations


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def now():
    return datetime.now(timezone.utc).isoformat()


def empty_state():
    return {"id": str(uuid4()), "revision": 0, "draft_input": {
        "profile": "H3-Base-Ref2VA", "request": "", "active_units": [], "pictures": [], "dialogues": [],
        "continuity": {"mode": "none", "declared_state": None}, "declared_duration_s": None, "ambient_sound": True},
        "state": "draft", "next_subject": 1, "next_dialogue": 1,
        "picture_registry_version": 1, "picture_ids": [], "subject_numbers": [], "legacy_picture_ids": {},
        "jobs": {}, "latest_job_id": None, "versions": [], "latest_candidate_id": None,
        "manual_version_id": None, "confirmed_version_id": None, "reference_revisions": {}, "unit_revisions": {}}


class Repository(LibraryOperations, ShotLibraryOperations, SubjectOperations, ArchiveOperations, ContinuityOperations, CutOperations):
    def __init__(self, data_dir):
        self.directory = Path(data_dir).resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / "workspace.sqlite3"
        self.lock = threading.RLock()
        # Modalità privata anche durante la creazione di WAL/SHM e dei media.
        self.path.touch(mode=0o600, exist_ok=True)
        os.chmod(self.path, 0o600)
        with closing(self.connect()) as source:
            exists = source.execute("SELECT 1 FROM sqlite_master WHERE name='settings'").fetchone()
            previous = source.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone() if exists else None
            if previous and previous[0] not in {'2', '3', '4', '5', '6', '7', '8'}:
                raise RuntimeError("Versione archivio non supportata; nessun dato modificato.")
            if previous and previous[0] in {'2', '3', '4', '5', '6', '7'}:
                backup = self.directory / {'2':'workspace.before-m3.sqlite3','3':'workspace.before-m4.sqlite3','4':'workspace.before-m6.sqlite3','5':'workspace.before-scene-subjects.sqlite3','6':'workspace.before-camera-presets.sqlite3','7':'workspace.before-library-trash.sqlite3'}[previous[0]]
                if not backup.exists():
                    backup.touch(mode=0o600)
                    with closing(sqlite3.connect(backup)) as target:
                        source.backup(target)
        with closing(self.connect()) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript('''
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, trashed INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS scenes (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), number INTEGER NOT NULL,
                    title TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0, finalized INTEGER NOT NULL DEFAULT 0,
                    trashed INTEGER NOT NULL DEFAULT 0, UNIQUE(project_id,number));
                CREATE TABLE IF NOT EXISTS cuts (
                    id TEXT PRIMARY KEY, scene_id TEXT NOT NULL REFERENCES scenes(id), number INTEGER NOT NULL,
                    title TEXT NOT NULL, data TEXT NOT NULL, UNIQUE(scene_id,number));
                CREATE TABLE IF NOT EXISTS versions (
                    id TEXT PRIMARY KEY, cut_id TEXT NOT NULL REFERENCES cuts(id), data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, cut_id TEXT NOT NULL REFERENCES cuts(id), data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS commands (
                    id TEXT PRIMARY KEY, operation TEXT NOT NULL, resource_id TEXT NOT NULL,
                    payload_hash TEXT NOT NULL, result TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS media (
                    id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, relative_path TEXT NOT NULL UNIQUE,
                    content_type TEXT NOT NULL, byte_size INTEGER NOT NULL, width INTEGER NOT NULL,
                    height INTEGER NOT NULL, display_name TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS project_references (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), data TEXT NOT NULL,
                    revision INTEGER NOT NULL, media_id TEXT REFERENCES media(id));
                CREATE TABLE IF NOT EXISTS project_units (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), subject INTEGER NOT NULL,
                    data TEXT NOT NULL, revision INTEGER NOT NULL, retained INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(project_id,subject));
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY, cut_id TEXT NOT NULL REFERENCES cuts(id),
                    version_id TEXT NOT NULL REFERENCES versions(id), created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS jobs_cut ON jobs(cut_id);
                CREATE INDEX IF NOT EXISTS versions_cut ON versions(cut_id);
                CREATE TABLE IF NOT EXISTS assistance_jobs (
                    id TEXT PRIMARY KEY, cut_id TEXT NOT NULL REFERENCES cuts(id), kind TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS assistance_cache (key TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS vision_trials (digest TEXT PRIMARY KEY, model TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS reference_proxies (
                    reference_id TEXT PRIMARY KEY REFERENCES project_references(id), media_id TEXT NOT NULL REFERENCES media(id));
                CREATE TABLE IF NOT EXISTS audio_media (
                    id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, relative_path TEXT NOT NULL,
                    preview_path TEXT NOT NULL, content_type TEXT NOT NULL, byte_size INTEGER NOT NULL,
                    sample_rate INTEGER NOT NULL, sample_count INTEGER NOT NULL, channels INTEGER NOT NULL,
                    duration_s REAL NOT NULL, display_name TEXT NOT NULL, created_at TEXT NOT NULL, preview_sha256 TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS video_media (
                    id TEXT PRIMARY KEY, sha256 TEXT NOT NULL UNIQUE, relative_path TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS cut_outputs (
                    cut_id TEXT NOT NULL REFERENCES cuts(id), version_id TEXT NOT NULL REFERENCES versions(id),
                    media_id TEXT NOT NULL REFERENCES video_media(id), PRIMARY KEY(cut_id,version_id));
                CREATE TABLE IF NOT EXISTS pending_file_deletions (relative_path TEXT PRIMARY KEY, sha256 TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS scene_subjects (
                    scene_id TEXT NOT NULL REFERENCES scenes(id), subject INTEGER NOT NULL,
                    unit_id TEXT NOT NULL REFERENCES project_units(id),
                    PRIMARY KEY(scene_id,subject), UNIQUE(scene_id,unit_id));
                CREATE TABLE IF NOT EXISTS version_subjects (
                    version_id TEXT NOT NULL REFERENCES versions(id), subject INTEGER NOT NULL,
                    unit_id TEXT NOT NULL REFERENCES project_units(id), PRIMARY KEY(version_id,subject));
                CREATE TABLE IF NOT EXISTS project_camera_presets (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    tag TEXT NOT NULL, data TEXT NOT NULL, UNIQUE(project_id,tag));
                CREATE TABLE IF NOT EXISTS library_trash (
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL CHECK(kind IN ('picture','unit')), reference_id TEXT NOT NULL,
                    trashed_at TEXT NOT NULL, PRIMARY KEY(project_id,kind,reference_id));
            ''')
        with self.transaction() as db:
            version = db.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()
            if version and version[0] not in {'2', '3', '4', '5', '6', '7', '8'}:
                raise RuntimeError("Versione archivio non supportata; nessun dato modificato.")
            if not version:
                self._initialize(db)
                db.execute("INSERT INTO settings VALUES ('schema_version','8')")
            elif version[0] in {'2', '3', '4', '5', '6', '7'}:
                db.execute("UPDATE settings SET value='8' WHERE key='schema_version'")
            if not version or version[0] in {'2', '3', '4', '5'}:self._initialize_scene_subjects(db)
        self._recover_interrupted()
        self.cleanup_files()

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @contextmanager
    def transaction(self):
        # Nessuna copia in memoria condivisa tra richieste o browser. Il lock
        # SQLite protegge anche accessi da connessioni/processi distinti.
        with self.lock:
            db = self.connect()
            try:
                db.execute("BEGIN IMMEDIATE")
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

    def _initialize(self, db):
        original = self.directory / "workspace.json"
        state, receipts = empty_state(), {}
        if original.exists():
            previous = original.read_bytes()
            backup = self.directory / "workspace.before-sqlite.json"
            if backup.exists() and backup.read_bytes() != previous:
                raise RuntimeError("Backup SQLite già presente ma diverso: conservare entrambi prima di riprovare.")
            if not backup.exists():
                with backup.open('xb') as file:
                    os.chmod(backup, 0o600)
                    file.write(previous); file.flush(); os.fsync(file.fileno())
            # Il lettore storico opera solo su una copia temporanea di QUESTO
            # archivio M1. Il JSON originale non viene riscritto o importato altrove.
            from app.legacy_store import LegacyRepository
            with tempfile.TemporaryDirectory(dir=self.directory) as temporary:
                (Path(temporary) / 'workspace.json').write_bytes(previous)
                legacy = LegacyRepository(temporary)
                state = copy.deepcopy(legacy._state)
            receipts = state.pop('commands', {})
            db.execute("INSERT INTO settings VALUES ('m1_sha256',?)", (digest(json.loads(previous)),))
        project_id, scene_id = str(uuid4()), str(uuid4())
        self._insert_project(db, project_id, "Progetto iniziale")
        db.execute("INSERT INTO scenes(id,project_id,number,title) VALUES (?,?,1,?)",
                   (scene_id, project_id, "Scena iniziale"))
        self._insert_cut(db, scene_id, state, 1, "Cut 1")
        state.update(scene_id=scene_id,project_id=project_id)
        self._sync_catalogue(db, state, empty_state(), project_id)
        for id in state.get('picture_ids', []):
            db.execute('INSERT OR IGNORE INTO project_references VALUES (?,?,?,1,NULL)',
                       (id, project_id, encode({'name': '', 'role': 'identity', 'description_en': '', 'confirmed': False})))
        for subject in state.get('subject_numbers', []):
            db.execute('INSERT OR IGNORE INTO project_units VALUES (?,?,?,?,1,0)',
                       (str(uuid4()), project_id, subject, encode({'subject': subject, 'name': '', 'role': 'character',
                                                               'description_en': '', 'confirmed': False, 'sources': []})))
        self._write_cut(db, state)
        for command_id, receipt in receipts.items():
            db.execute("INSERT INTO commands VALUES (?,?,?,?,?)", (command_id, 'legacy', state['id'],
                       receipt['payload_hash'], encode({'kind': 'legacy', 'receipt': receipt})))
        db.execute("INSERT INTO settings VALUES ('default_cut',?)", (state['id'],))
        # Verifica la conversione prima del commit; testo/hash/ID restano esatti.
        saved = self._load(db, state['id'])
        for key in ('id', 'revision', 'draft_input', 'versions', 'jobs', 'latest_candidate_id', 'manual_version_id'):
            if saved[key] != state[key]:
                raise RuntimeError(f"Migrazione non verificata: {key}. JSON e backup conservati.")

    def _insert_project(self, db, id, name):
        timestamp = now()
        db.execute("INSERT INTO projects(id,name,revision,created_at,updated_at) VALUES (?,?,0,?,?)",
                   (id, name, timestamp, timestamp))

    def _insert_cut(self, db, scene_id, state, number, title):
        db.execute("INSERT INTO cuts VALUES (?,?,?,?,?)", (state['id'], scene_id, number, title, '{}'))
        self._write_cut(db, state)

    def _load(self, db, cut_id, *, active=False):
        row = db.execute('''SELECT c.*,s.project_id,s.trashed AS scene_trashed,s.finalized,
                            p.trashed AS project_trashed FROM cuts c JOIN scenes s ON c.scene_id=s.id
                            JOIN projects p ON s.project_id=p.id WHERE c.id=?''', (str(cut_id),)).fetchone()
        if row is None or (active and (row['scene_trashed'] or row['project_trashed'])):
            raise StoreError('not_found', 'Cut non trovato o nel cestino.', 404)
        state = json.loads(row['data'])
        if active and state.get('trashed'):
            raise StoreError('cut_trashed', 'Il cut è nel cestino. Puoi ripristinarlo da «Gestisci nomi e cestino».', 404)
        state.update(id=row['id'], scene_id=row['scene_id'], project_id=row['project_id'],
                     number=row['number'], title=row['title'], finalized=bool(row['finalized']))
        state['versions'] = [json.loads(v['data']) for v in db.execute('SELECT data FROM versions WHERE cut_id=? ORDER BY rowid', (row['id'],))]
        state['jobs'] = {v['id']: json.loads(v['data']) for v in db.execute('SELECT id,data FROM jobs WHERE cut_id=? ORDER BY rowid', (row['id'],))}
        state['picture_ids'] = [r[0] for r in db.execute('SELECT id FROM project_references WHERE project_id=?', (row['project_id'],))]
        state['subject_numbers'] = [r[0] for r in db.execute('SELECT subject FROM scene_subjects WHERE scene_id=?', (row['scene_id'],))]
        return state

    def _write_cut(self, db, state):
        excluded = {'jobs', 'versions', 'commands', 'scene_id', 'project_id', 'number', 'title', 'finalized', 'picture_ids', 'subject_numbers'}
        db.execute('UPDATE cuts SET data=? WHERE id=?', (encode({k: v for k, v in state.items() if k not in excluded}), state['id']))
        for version in state.get('versions', []):
            db.execute('INSERT OR IGNORE INTO versions VALUES (?,?,?)', (version['id'], state['id'], encode(version)))
        for job in state.get('jobs', {}).values():
            db.execute('INSERT INTO jobs VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                       (job['id'], state['id'], encode(job)))

    @staticmethod
    def _reference_data(picture):
        result = {'description_language': 'English', 'use_original_language': False, 'original_description': None, 'original_language': None,
                **{k: v for k, v in picture.items() if k not in {'id', 'slot', 'linked_to_h3', 'guidance', 'excluded'}}}
        settings = normalized_settings(result.get('analysis'))
        if settings is None: result.pop('analysis', None)
        else: result['analysis'] = settings
        return result

    @staticmethod
    def _unit_data(unit):
        value = copy.deepcopy(unit)
        value.pop('excluded', None)
        if value.get('scale'):
            value['scale'] = canonical_scale(value)
        else:
            value.pop('scale', None)
        if not value.get('physical_details'): value.pop('physical_details', None)
        for detail in value.get('physical_details', []):
            if not isinstance(detail, dict): continue
            if detail.get('origin') == 'picture': detail.pop('origin')
            if detail.get('picture_id') is None: detail.pop('picture_id', None)
        if value.get('definition_mode') == 'picture': value.pop('definition_mode')
        sources = value.get('sources', [])
        for source in sources if isinstance(sources, list) else []:
            if isinstance(source, dict) and source.get('origin') == 'picture': source.pop('origin')
        return value

    def _sync_catalogue(self, db, state, previous, project_id):
        for key, table, identity, revisions in [('pictures', 'project_references', 'id', 'reference_revisions'),
                                               ('active_units', 'project_units', 'subject', 'unit_revisions')]:
            old = {v[identity]: v for v in previous.get('draft_input', {}).get(key, [])}
            revision_map = state.setdefault(revisions, {})
            for item in state['draft_input'].get(key, []):
                id = item[identity]
                data = self._reference_data(item) if key == 'pictures' else self._unit_data(item)
                before = old.get(id)
                before = (self._reference_data(before) if key == 'pictures' else self._unit_data(before)) if before else None
                column = 'id' if key == 'pictures' else 'subject'
                row = (self._scene_unit(db,state['scene_id'],id) if key == 'active_units' else
                       db.execute(f'SELECT * FROM {table} WHERE project_id=? AND {column}=?', (project_id, id)).fetchone())
                if key == 'active_units' and row:
                    # Il numero della scena non fa parte dell'identità canonica.
                    data['subject'] = row['subject']
                    if before:before['subject'] = row['subject']
                if key == 'active_units' and row and data.get('sources') and all(isinstance(s, dict) and s.get('origin') == 'context' for s in data['sources']):
                    canonical = self._unit_data(json.loads(row['data']))
                    if any(s.get('origin', 'picture') == 'picture' and s.get('picture_id') for s in canonical.get('sources', []) if isinstance(s, dict)):
                        if 'definition_mode' in canonical: data['definition_mode'] = canonical['definition_mode']
                        else: data.pop('definition_mode', None)
                        # Il raccordo cambia la provenienza nel cut, non cancella
                        # le immagini canoniche riutilizzabili nella libreria.
                        unchanged_context = before is not None and all(data.get(k) == before.get(k) for k in ['name','role','description_en','physical_details','scale'])
                        context_details = all(d.get('origin') == 'context' for d in data.get('physical_details', []))
                        new_context = before is None and context_details and all(data.get(k) == canonical.get(k) for k in ['name','role'])
                        if unchanged_context or new_context or (context_details and all(data.get(k) == canonical.get(k) for k in ['name','role','description_en','scale']) and detail_content(data) == detail_content(canonical)):
                            data = canonical
                        else:
                            data['sources'] = canonical['sources']
                            canonical_details = {d['id']: d for d in canonical.get('physical_details', [])}
                            for detail in data.get('physical_details', []):
                                original = canonical_details.get(detail.get('id'))
                                if detail.get('origin') == 'context' and original:
                                    detail['origin'] = original.get('origin', 'picture')
                                    detail['picture_id'] = original.get('picture_id')
                if row is None:
                    if key == 'pictures':
                        db.execute('INSERT INTO project_references VALUES (?,?,?,1,NULL)', (id, project_id, encode(data)))
                    else:
                        unit_id = str(uuid4())
                        occupied = db.execute('SELECT 1 FROM project_units WHERE project_id=? AND subject=?',(project_id,id)).fetchone()
                        canonical_number = db.execute('SELECT coalesce(max(subject),0)+1 FROM project_units WHERE project_id=?',(project_id,)).fetchone()[0] if occupied else id
                        data['subject'] = canonical_number
                        db.execute('INSERT INTO project_units VALUES (?,?,?,?,1,?)',
                                   (unit_id, project_id, canonical_number, encode(data), int(bool(data.get('confirmed') and data.get('name')))))
                        db.execute('INSERT INTO scene_subjects VALUES (?,?,?)',(state['scene_id'],id,unit_id))
                        state.setdefault('unit_bindings', {})[str(id)] = unit_id
                    revision_map[str(id)] = 1
                elif before != data:
                    current = json.loads(row['data'])
                    current = self._reference_data(current) if key == 'pictures' else self._unit_data(current)
                    expected = revision_map.get(str(id), previous.get(revisions, {}).get(str(id), row['revision']))
                    # Una revisione può essere avanzata e poi tornata allo stesso
                    # contenuto della base del cut. In quel caso nessun dato più
                    # recente viene sovrascritto: le modifiche locali sono sicure.
                    same_base = current == before
                    if key == 'pictures' and same_base and expected != row['revision']:
                        # Una foto/proxy sostituita è un cambiamento reale anche
                        # quando nome e descrizione sono rimasti identici.
                        base_media = (previous.get('media_bindings', {}).get(str(id)) or {}).get('id')
                        base_proxy = (previous.get('proxy_bindings', {}).get(str(id)) or {}).get('id')
                        proxy = db.execute('SELECT media_id FROM reference_proxies WHERE reference_id=?', (str(id),)).fetchone()
                        same_base = row['media_id'] == base_media and (proxy['media_id'] if proxy else None) == base_proxy
                    if expected != row['revision'] and current != data and not same_base:
                        label = f"Picture {item.get('slot', '?')}" if key == 'pictures' else f'Subject {id}'
                        if item.get('name'): label += ' · ' + str(item['name'])
                        raise StoreError('reference_conflict', label + ': questo riferimento è cambiato in un altro cut. Conserva i campi locali e ricarica il riferimento dalla libreria.')
                    revision = row['revision'] + (current != data)
                    db.execute(f'UPDATE {table} SET data=?,revision=? WHERE id=?', (encode(data), revision, row['id']))
                    if key == 'active_units' and data.get('confirmed') and data.get('name'):
                        db.execute('UPDATE project_units SET retained=1 WHERE id=?', (row['id'],))
                    revision_map[str(id)] = revision
                else:
                    revision_map.setdefault(str(id), row['revision'])
                if key == 'active_units' and row:
                    state.setdefault('unit_bindings', {})[str(id)] = row['id']
        numbers = {r['unit_id']: r['subject'] for r in db.execute('SELECT * FROM scene_subjects WHERE scene_id=?', (state['scene_id'],))}
        for unit in state['draft_input'].get('active_units', []):
            resolve_scale_subject(unit, numbers)

    def _media_snapshot(self, db, data, state):
        ids = [p.get('id') for p in data.get('pictures', [])]
        result = {id: copy.deepcopy(state.get('media_bindings', {})[id]) for id in ids if id in state.get('media_bindings', {})}
        for audio in data.get('audio_references', []):
            row = db.execute('SELECT id,sha256 FROM audio_media WHERE id=?', (audio.get('media_id'),)).fetchone()
            if row: result['audio:' + audio['id']] = dict(row) | {'kind': 'audio'}
        continuity = data.get('continuity') or {}
        for video in data.get('videos', []):
            if video.get('id') != continuity.get('video_id') and not (video.get('guidance') or {}).get('enabled'): continue
            row = db.execute('SELECT id,sha256 FROM video_media WHERE id=?', (video.get('media_id'),)).fetchone()
            if row: result['video:' + video['id']] = dict(row) | {'kind': 'video'}
        if continuity.get('context_media_id'):
            table = 'video_media' if continuity.get('context_media_kind') == 'video' else 'media'
            row = db.execute(f'SELECT id,sha256 FROM {table} WHERE id=?', (continuity['context_media_id'],)).fetchone()
            if row: result['continuity_context'] = dict(row) | {'kind': 'video' if table == 'video_media' else 'image'}
        return result

    def _confirmation_issues(self, db, version, *, verify_files=False):
        issues = list(version.get('issues', []))
        if not version.get('structural_checks_passed'):
            issues.append('I controlli strutturali della versione non sono superati.')
        snapshot = version.get('input_snapshot')
        if not snapshot:
            issues.append('Questa versione storica non ha uno snapshot verificabile: ricompila o salva una nuova versione manuale.')
        else:
            try:
                CompileInput.model_validate(snapshot)
            except Exception:
                issues.append('Lo snapshot contiene riferimenti o dati da confermare.')
        duration = version.get('duration_s')
        if type(duration) not in (int, float) or not 4 <= duration <= 15:
            issues.append('Durata utile non disponibile fra 4 e 15 secondi.')
        issues.extend(self._media_issues(db, self._participating_media(version.get('media_snapshot', {}), snapshot), verify_files=verify_files))
        return list(dict.fromkeys(issues))

    def _participating_media(self, media, raw):
        if not isinstance(raw, dict) or not any(isinstance(item,dict) and item.get('excluded') is True for key in ['pictures','active_units'] for item in raw.get(key) or []):
            return media
        try:
            data = CompileInput.model_validate(raw)
        except Exception:
            return media  # Snapshot non valido: conserva i controlli prudenti.
        unused = {p.id for p in data.pictures or []} - {p.id for p in data.active_pictures}
        return {key:value for key,value in media.items() if key not in unused}

    def _media_issues(self, db, snapshot, *, verify_files=False):
        issues = []
        for media in snapshot.values():
            table = {'audio': 'audio_media', 'video': 'video_media'}.get(media.get('kind'), 'media')
            row = db.execute(f'SELECT * FROM {table} WHERE id=?', (media['id'],)).fetchone()
            if not row or row['sha256'] != media['sha256'] or not (self.directory / row['relative_path']).is_file():
                issues.append('Un media dello snapshot non è disponibile nell’archivio gestito.')
            elif verify_files:
                path = (self.directory / row['relative_path']).resolve()
                root = {'audio': 'audio', 'video': 'video'}.get(media.get('kind'), 'media')
                if not path.is_relative_to((self.directory / root).resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != media['sha256']:
                    issues.append('Un media dello snapshot non corrisponde al file originale archiviato.')
        return list(dict.fromkeys(issues))

    def _view(self, state, db=None):
        if db is None:
            with closing(self.connect()) as connection:
                return self._view(state, connection)
        versions = copy.deepcopy(state['versions'])
        approved = {r[0] for r in db.execute('SELECT version_id FROM approvals WHERE cut_id=?', (state['id'],))}
        for version in versions:
            version['user_approved'] = version['id'] in approved
        latest = state['jobs'].get(state.get('latest_job_id'))
        unit_rows = db.execute('SELECT unit_id AS id,subject FROM scene_subjects WHERE scene_id=?', (state['scene_id'],)).fetchall()
        media = {}
        for picture in state['draft_input'].get('pictures', []):
            binding = state.get('media_bindings', {}).get(picture['id'])
            row = db.execute('SELECT * FROM media WHERE id=?', (binding['id'],)).fetchone() if binding else None
            if row:
                media[picture['id']] = self.media_view(row)
        fields = {k: state[k] for k in ['id', 'revision', 'draft_input', 'state', 'latest_candidate_id', 'manual_version_id',
                  'scene_id', 'project_id', 'number', 'title']}
        fields.update(versions=versions, latest_job=self._job_view(state, latest).model_dump(mode='json') if latest else None,
                      confirmed_version_id=state.get('confirmed_version_id'), catalogue_issues=self._catalogue_issues(state['draft_input']),
                      media_by_picture=media, reference_revisions=state.get('reference_revisions', {}), unit_revisions=state.get('unit_revisions', {}),
                      unit_ids={str(r['subject']): r['id'] for r in unit_rows},
                      confirmation_issues={v['id']: self._confirmation_issues(db, v) for v in versions})
        data = state['draft_input']
        used_pictures = {id for u in data.get('active_units', []) if not u.get('excluded') for id in unit_picture_ids(u)}
        fields['tokens'] = ([{'kind': 'unit', 'id': str(u['subject']), 'label': f"{u.get('name') or 'Unità'} · Subject {u['subject']}",
                              'token': f"<Subject {u['subject']}>"} for u in data.get('active_units', []) if not u.get('excluded')] +
                            [{'kind': 'picture', 'id': p['id'], 'label': f"{p.get('name') or 'Immagine'} · Picture {p['slot']}",
                             'token': f"<Picture {p['slot']}>",
                             'association': 'bound' if p['id'] in used_pictures else 'required'}
                             for p in data.get('pictures', []) if not p.get('excluded') and type(p.get('slot')) is int and 1 <= p['slot'] <= 9] +
                            [{'kind': 'dialogue', 'id': d['id'], 'label': f"Battuta {d['id']}", 'token': f"battuta {d['id']}"}
                             for d in data.get('dialogues', [])])
        fields['tokens'] += [{'kind': 'audio', 'id': a['id'], 'label': f"{a.get('name') or 'Audio'} · Audio {a['slot']}", 'token': f"<Audio {a['slot']}>"}
                             for a in data.get('audio_references', []) if type(a.get('slot')) is int]
        from app.assistance import public_job
        from app.media import AudioStore
        fields['assistance_jobs'] = [public_job(json.loads(r['data']), state) for r in db.execute('SELECT data FROM assistance_jobs WHERE cut_id=? ORDER BY rowid', (state['id'],))]
        fields['proxy_by_picture'] = {}
        for id, binding in state.get('proxy_bindings', {}).items():
            row = db.execute('SELECT * FROM media WHERE id=?', (binding['id'],)).fetchone()
            if row: fields['proxy_by_picture'][id] = self.media_view(row)
        fields['audio_media'] = {}
        for audio in data.get('audio_references', []):
            row = db.execute('SELECT * FROM audio_media WHERE id=?', (audio.get('media_id'),)).fetchone()
            if row: fields['audio_media'][audio['id']] = AudioStore.view(row)
        fields.update(self.continuity_view(db, state))
        fields['reference_updates'] = [r['id'] for r in db.execute('SELECT id,revision FROM project_references WHERE project_id=?', (state['project_id'],))
            if r['id'] in {p['id'] for p in data.get('pictures', [])} and r['revision'] != state.get('reference_revisions', {}).get(r['id'])]
        fields['camera_presets'] = self._camera_presets(db, state['project_id'])
        fields['tokens'] += [{'kind': 'video', 'id': v['id'], 'label': f"{v.get('name') or 'Video'} · Video {v['slot']}", 'token': f"<Video {v['slot']}>"}
                            for v in data.get('videos', []) if type(v.get('slot')) is int]
        return dto(CutView, fields)

    def workspace(self, cut_id=None):
        with closing(self.connect()) as db:
            if cut_id is None:
                default=db.execute("SELECT value FROM settings WHERE key='default_cut'").fetchone()
                active=db.execute('''SELECT c.id FROM cuts c JOIN scenes s ON s.id=c.scene_id JOIN projects p ON p.id=s.project_id
                    WHERE s.trashed=0 AND p.trashed=0 AND COALESCE(json_extract(c.data,'$.trashed'),0)=0
                    ORDER BY p.created_at,s.number,c.number''').fetchall()
                ids=[r[0] for r in active]
                cut_id=default[0] if default and default[0] in ids else ids[0] if ids else None
                if cut_id is None:raise StoreError('empty_archive','Non ci sono cut attivi. Crea o ripristina un progetto.',404)
            return self._view(self._load(db, cut_id, active=True), db)

    def preview_dialogues(self, cut_id):
        with closing(self.connect()) as db:
            state=self._load(db,cut_id,active=True)
            request=state['draft_input'].get('request','')
            return dict(revision=state['revision'],source_request=request,candidates=quoted_speech(request))

    def import_dialogues(self, cut_id, command):
        def action(state):
            data=state['draft_input']
            if data.get('request')!=command.source_request:
                raise StoreError('revision_conflict','La richiesta è cambiata: rileggi le battute prima di importarle.')
            if data.get('dialogues') or any(a.get('role')=='speech' for a in data.get('audio_references',[])):
                raise StoreError('invalid_input','Sono già presenti battute: usa i loro ID nella richiesta per evitare duplicati.',422)
            candidates={c['index']:c for c in quoted_speech(command.source_request)}
            selected=[d.index for d in command.dialogues]
            speakers={u['subject'] for u in data.get('active_units',[]) if u.get('role')=='character'}
            if len(selected)!=len(set(selected)) or any(i not in candidates for i in selected):
                raise StoreError('invalid_input','La selezione delle citazioni non è valida. Riapri l’anteprima.',422)
            if any((d.speaker_subject is not None if d.delivery == 'narrator' else
                    d.speaker_subject not in speakers or d.narrator_voice is not None)
                   or not d.text.strip() or '<' in d.text or '{{' in d.text for d in command.dialogues):
                raise StoreError('invalid_input','Controlla testo e parlante di ogni battuta selezionata.',422)
            request=command.source_request
            # L'ordine nella richiesta governa sia gli ID sia gli eventi, non
            # l'ordine delle selezioni inviate dal browser.
            replacements=[]
            for choice in sorted(command.dialogues,key=lambda d:candidates[d.index]['start']):
                candidate=candidates[choice.index];id=self._available_dialogue(state)
                data.setdefault('dialogues',[]).append(dict(id=id,origin='native',confirmed=True,
                    **choice.model_dump(exclude={'index'})))
                replacements.append((candidate['start'],candidate['end'],f'pronuncia la battuta {id}'))
            for start,end,replacement in reversed(replacements):request=request[:start]+replacement+request[end:]
            data['request']=request;state['state']='draft'
        return self._command('import_dialogues',cut_id,command,action)[0]

    def _compact_view(self, view):
        value = view.model_dump(mode='json')
        value['approved_ids'] = [v['id'] for v in value['versions'] if v['user_approved']]
        value['version_ids'] = [v['id'] for v in value.pop('versions')]
        latest = value.get('latest_job')
        if latest:
            latest['result_present'] = latest.pop('result') is not None
        return {'kind': 'cut', 'view': value}

    def _replay(self, db, state, saved):
        if saved['kind'] == 'job':
            return self._job_view(state, state['jobs'][saved['id']])
        if saved['kind'] == 'legacy':
            receipt = saved['receipt']
            if receipt.get('job_id'):
                return self._job_view(state, state['jobs'][receipt['job_id']])
            value = copy.deepcopy(receipt['response'])
            value['draft_input'] = self._upgrade_legacy_draft(value['draft_input'], state)
            value['catalogue_issues'] = self._catalogue_issues(value['draft_input'])
            return dto(CutView, value)
        value = copy.deepcopy(saved['view'])
        approved = set(value.pop('approved_ids', []))
        value['versions'] = [json.loads(db.execute('SELECT data FROM versions WHERE id=?', (id,)).fetchone()[0]) for id in value.pop('version_ids')]
        for version in value['versions']:
            version['user_approved'] = version['id'] in approved
        latest = value.get('latest_job')
        if latest:
            latest['result'] = state['jobs'][latest['id']]['result'] if latest.pop('result_present') else None
        return dto(CutView, value)

    def _command(self, operation, cut_id, command, action, *, allow_finalized=False):
        with self.transaction() as db:
            state = self._load(db, cut_id, active=True)
            receipt = db.execute('SELECT * FROM commands WHERE id=?', (str(command.command_id),)).fetchone()
            if receipt:
                if receipt['resource_id'] != str(cut_id) or receipt['payload_hash'] not in self._receipt_hashes(operation, cut_id, command):
                    raise StoreError('command_conflict', 'Questo comando è già stato usato con dati diversi.')
                return self._replay(db, state, json.loads(receipt['result'])), False
            if command.expected_revision != state['revision']:
                raise StoreError('revision_conflict', 'La bozza è cambiata: recuperare la versione server senza perdere il testo locale.', current_revision=state['revision'])
            if state['finalized'] and not allow_finalized:
                raise StoreError('scene_finalized', 'La scena è terminata. Riaprila prima di modificare i cut.')
            previous = copy.deepcopy(state)
            state['revision'] += 1
            # L'allocatore deve vedere tutti i cut dello stesso progetto.
            self._transaction_db = db
            try:
                job_id = action(state)
            finally:
                self._transaction_db = None
            self._sync_catalogue(db, state, previous, state['project_id'])
            old_audio = {a['id']: a for a in previous['draft_input'].get('audio_references', [])}
            for audio in state['draft_input'].get('audio_references', []):
                if audio != old_audio.get(audio['id']):
                    epochs = state.setdefault('audio_epochs', {})
                    epochs[audio['id']] = epochs.get(audio['id'], 0) + 1
            if job_id:
                state['jobs'][job_id]['unit_snapshot'] = {str(u['subject']):state['unit_bindings'][str(u['subject'])] for u in state['jobs'][job_id]['input'].get('active_units',[])}
                state['jobs'][job_id]['media_snapshot'] = self._media_snapshot(db, state['draft_input'], state)
                issues = self._media_issues(db, self._participating_media(state['jobs'][job_id]['media_snapshot'], state['jobs'][job_id]['input']), verify_files=True)
                if issues:
                    raise StoreError('media_unavailable', ' '.join(issues), 422)
            for version in state['versions'][len(previous['versions']):]:
                version['media_snapshot'] = self._media_snapshot(db, state['draft_input'], state)
            self._write_cut(db, state)
            for version in state['versions'][len(previous['versions']):]:
                for unit in (version.get('input_snapshot') or {}).get('active_units',[]):
                    identity = state.get('unit_bindings',{}).get(str(unit['subject']))
                    if identity:db.execute('INSERT INTO version_subjects VALUES (?,?,?)',(version['id'],unit['subject'],identity))
            response = self._job_view(state, state['jobs'][job_id]) if job_id else self._view(state, db)
            result = {'kind': 'job', 'id': job_id} if job_id else self._compact_view(response)
            payload_hash = digest({'operation': operation, 'cut_id': str(cut_id), 'command': command.model_dump(mode='json')})
            db.execute('INSERT INTO commands VALUES (?,?,?,?,?)', (str(command.command_id), operation, str(cut_id), payload_hash, encode(result)))
            return response, True

    def _job_view(self, state, job):
        return super()._job_view(state, {k: v for k, v in job.items() if k not in {'media_snapshot','unit_snapshot'}})

    def _registered(self, state, data):
        super()._registered(state, data)
        self._check_continuity_links(self._transaction_db, state, data)
        for unit in data.get('active_units', []):
            previous = state.get('unit_bindings', {}).get(str(unit['subject']))
            row = self._scene_unit(self._transaction_db,state['scene_id'],unit['subject'])
            if previous and row and previous != row['id']:
                raise StoreError('reference_conflict', 'Il numero provvisorio è stato riutilizzato per una nuova unità. Scegli il Subject dalla libreria, senza ripristinare un’associazione precedente.')
            scale = unit.get('scale')
            if isinstance(scale, dict) and scale.get('reference_subject') is not None:
                target = self._scene_unit(self._transaction_db, state['scene_id'], scale['reference_subject'])
                if not target or target['id'] != scale.get('reference_subject_id'):
                    raise StoreError('invalid_input', f"Subject {unit['subject']} — l’identità del Subject di confronto dimensionale non corrisponde alla scena: selezionalo di nuovo.", 422)
        audios = data.get('audio_references', [])
        if not isinstance(audios, list) or any(not isinstance(a, dict) or a.get('id') not in state.get('audio_ids', []) for a in audios):
            raise StoreError('invalid_input', 'Usa gli slot audio aggiunti dal server.', 422)
        for audio in audios:
            if audio.get('media_id') is None: continue
            row = self._transaction_db.execute('SELECT * FROM audio_media WHERE id=?', (audio['media_id'],)).fetchone()
            if not row or any(audio.get(k) != row[k] for k in ['sample_rate', 'sample_count', 'channels']) or audio.get('measured_duration_s') != row['duration_s']:
                raise StoreError('invalid_input', 'I metadati audio devono corrispondere ai campioni del file gestito.', 422)

    def add_item(self, cut_id, command):
        if command.kind == 'video': return self.add_video_item(cut_id, command)
        if command.kind != 'audio': return super().add_item(cut_id, command)
        def action(state):
            audios = state['draft_input'].setdefault('audio_references', [])
            used = {a.get('slot') for a in audios}
            slot = next((n for n in range(1, 4) if n not in used), None)
            if slot is None: raise StoreError('invalid_input', 'Il cut ammette al massimo tre slot audio.', 422)
            number = state.get('next_audio_event', 1); state['next_audio_event'] = number + 1
            id = f'a{number}'; state.setdefault('audio_ids', []).append(id)
            audios.append({'id': id, 'slot': slot, 'media_id': None, 'name': '', 'mode': 'copy', 'role': 'speech',
                'measured_duration_s': None, 'sample_rate': None, 'sample_count': None, 'channels': None,
                'segment_start_s': 0.0, 'segment_end_s': None, 'offset_s': 0.0, 'speaker_subject': None,
                'language': 'Italian', 'transcript': '', 'description_en': '', 'confirmed': False,
                'linked_to_h3': False, 'exclusive_full_track': False})
            state['state'] = 'draft'
        return self._command('item', cut_id, command, action)[0]

    def attach_audio(self, cut_id, audio_id, command):
        def action(state):
            row = self._transaction_db.execute('SELECT * FROM audio_media WHERE id=?', (str(command.media_id),)).fetchone()
            audio = next((a for a in state['draft_input'].get('audio_references', []) if a['id'] == audio_id), None)
            if row is None or audio is None: raise StoreError('not_found', 'Audio o slot non trovato.', 404)
            audio.update(media_id=row['id'], name=audio.get('name') or row['display_name'], measured_duration_s=row['duration_s'],
                         sample_rate=row['sample_rate'], sample_count=row['sample_count'], channels=row['channels'],
                         segment_start_s=0.0, segment_end_s=None, transcript='', confirmed=False, linked_to_h3=False)
            state['state'] = 'draft'
        return self._command(f'attach_audio:{audio_id}', cut_id, command, action)[0]

    def _available_subject(self, state):
        db = self._transaction_db
        active = set()
        references = {}
        for row in db.execute(
            'SELECT id, number, data FROM cuts WHERE scene_id=? ORDER BY number', (state['scene_id'],)
        ):
            draft = state['draft_input'] if row['id'] == state['id'] else json.loads(row['data'])['draft_input']
            active.update(unit['subject'] for unit in draft.get('active_units', []))
            references[row['number']] = draft_subject_numbers(draft)
        number = 1
        while number in active:
            number += 1
        for cut_number, used in references.items():
            if number in used:
                raise StoreError(
                    'subject_references_unresolved',
                    f'Il Cut {cut_number} richiama ancora Subject {number}, che è stato rimosso. '
                    'Aggiorna il richiamo nella bozza, poi aggiungi il nuovo Subject.',
                    409,
                )
        # Job e versioni conservano il loro mapping per UUID. Si libera solo
        # il numero della scena, senza eliminare l'identità dalla libreria.
        db.execute('DELETE FROM scene_subjects WHERE scene_id=? AND subject=?', (state['scene_id'], number))
        return number

    def job(self, job_id):
        with closing(self.connect()) as db:
            row = db.execute('SELECT cut_id FROM jobs WHERE id=?', (str(job_id),)).fetchone()
            if not row:
                raise StoreError('not_found', 'Lavoro non trovato.', 404)
            state = self._load(db, row[0], active=True)
            return self._job_view(state, state['jobs'][str(job_id)])

    def text(self, cut_id, version_id):
        with closing(self.connect()) as db:
            self._load(db, cut_id, active=True)
            row = db.execute('SELECT data FROM versions WHERE id=? AND cut_id=?', (str(version_id), str(cut_id))).fetchone()
            if not row:
                raise StoreError('not_found', 'Versione non trovata.', 404)
            return json.loads(row[0])['text']

    def start_job(self, job_id):
        with self.transaction() as db:
            row = db.execute('SELECT cut_id FROM jobs WHERE id=?', (str(job_id),)).fetchone()
            if not row:
                return None
            state = self._load(db, row[0])
            job = state['jobs'][str(job_id)]
            if job['status'] != 'queued':
                return None
            job['status'] = 'running'
            if job['input_revision'] == state['revision']:
                state['state'] = 'compiling'
            self._write_cut(db, state)
            return CompileInput.model_validate(job['input']), job['model']

    def finish_job(self, job_id, result):
        with self.transaction() as db:
            row = db.execute('SELECT cut_id FROM jobs WHERE id=?', (str(job_id),)).fetchone()
            state = self._load(db, row[0])
            job = state['jobs'][str(job_id)]
            if job['status'] not in {'queued', 'running'}:
                return
            job['result'] = result.model_dump(mode='json')
            job['status'] = 'failed' if result.status == 'error' else 'succeeded'
            current = job['input_revision'] == state['revision']
            if result.status == 'proposal':
                version = PromptVersion(id=uuid4(), origin='generated', text=result.prompt,
                    input_hash=job['input_hash'], input_revision=job['input_revision'], duration_s=result.duration_s,
                    duration_origin=result.duration_origin, structural_checks_passed=result.structural_checks_passed,
                    issues=result.issues, input_snapshot=copy.deepcopy(job['input']),
                    media_snapshot=job.get('media_snapshot', {})).model_dump(mode='json')
                state['versions'].append(version)
                db.execute('INSERT INTO versions VALUES (?,?,?)',(version['id'],state['id'],encode(version)))
                for number,identity in job.get('unit_snapshot',{}).items():
                    db.execute('INSERT INTO version_subjects VALUES (?,?,?)',(version['id'],int(number),identity))
                job['candidate_id'] = version['id']
                if current:
                    state['latest_candidate_id'] = version['id']
            if current:
                state['state'] = result.status
            self._write_cut(db, state)

    def _recover_interrupted(self):
        with self.transaction() as db:
            for row in db.execute('SELECT id FROM cuts').fetchall():
                state = self._load(db, row[0])
                changed = False
                for job in state['jobs'].values():
                    if job['status'] in {'queued', 'running'}:
                        job['status'] = 'failed'
                        job['result'] = CompileResult(status='error', input_hash=job['input_hash'], error_code='interrupted',
                            issues=['Compilazione interrotta dal riavvio: ricompilare esplicitamente.']).model_dump(mode='json')
                        if job['input_revision'] == state['revision']:
                            state['state'] = 'error'
                        changed = True
                if changed:
                    self._write_cut(db, state)

    @staticmethod
    def media_view(row):
        return {k: row[k] for k in ['id', 'sha256', 'content_type', 'byte_size', 'width', 'height', 'display_name', 'created_at']}

    def _scene_view(self, db, row):
        cuts, trashed_cuts = [], []
        for cut in db.execute('SELECT * FROM cuts WHERE scene_id=? ORDER BY number', (row['id'],)):
            data = json.loads(cut['data'])
            approved = data.get('confirmed_version_id')
            version = db.execute('SELECT data FROM versions WHERE id=?', (approved,)).fetchone() if approved else db.execute('SELECT data FROM versions WHERE cut_id=? ORDER BY rowid DESC LIMIT 1', (cut['id'],)).fetchone()
            selected = json.loads(version[0]) if version else None
            output = db.execute('SELECT v.data FROM video_media v JOIN cut_outputs o ON o.media_id=v.id WHERE o.cut_id=? AND o.version_id=?',
                                (cut['id'], selected['id'])).fetchone() if selected else None
            target = trashed_cuts if data.get('trashed') else cuts
            target.append({'id': cut['id'], 'scene_id': row['id'], 'number': cut['number'], 'title': cut['title'],
                         'revision': data['revision'], 'state': data['state'], 'confirmed_version_id': approved,
                         'duration_s': selected.get('duration_s') if selected else None,
                         'duration_origin': selected.get('duration_origin') if selected else None,
                         'selected_version_id': selected['id'] if selected else None,
                         'output_duration_s': json.loads(output[0])['duration_s'] if output else None})
        return dto(SceneView, dict(row) | {'finalized': bool(row['finalized']), 'trashed': bool(row['trashed']),
                                          'cuts': cuts, 'trashed_cuts': trashed_cuts})

    def _project_view(self, db, row):
        scenes = [self._scene_view(db, scene).model_dump(mode='json') for scene in
                  db.execute('SELECT * FROM scenes WHERE project_id=? ORDER BY number', (row['id'],))]
        return dto(ProjectView, dict(row) | {'trashed': bool(row['trashed']), 'scenes': scenes})

    def projects(self):
        with closing(self.connect()) as db:
            return [self._project_view(db, row) for row in db.execute('SELECT * FROM projects ORDER BY created_at,id')]

    def _entity_command(self, operation, resource_id, command, action):
        hash = digest({'operation': operation, 'resource_id': str(resource_id), 'command': command.model_dump(mode='json')})
        with self.transaction() as db:
            receipt = db.execute('SELECT * FROM commands WHERE id=?', (str(command.command_id),)).fetchone()
            if receipt:
                if receipt['payload_hash'] != hash:
                    raise StoreError('command_conflict', 'Questo comando è già stato usato con dati diversi.')
                return json.loads(receipt['result'])['value']
            result = action(db)
            value = result.model_dump(mode='json') if hasattr(result, 'model_dump') else result
            db.execute('INSERT INTO commands VALUES (?,?,?,?,?)',
                       (str(command.command_id), operation, str(resource_id), hash, encode({'kind': 'entity', 'value': value})))
            return value

    def _entity(self, db, table, id, revision=None, *, active=True):
        row = db.execute(f'SELECT * FROM {table} WHERE id=?', (str(id),)).fetchone()
        if row is None or (active and row['trashed']):
            raise StoreError('not_found', 'Elemento non trovato o nel cestino.', 404)
        if table == 'scenes':
            project = self._entity(db, 'projects', row['project_id'], active=active)
        if revision is not None and row['revision'] != revision:
            raise StoreError('revision_conflict', 'Il salvataggio è cambiato in un altro browser. Ricarica l’elenco.', current_revision=row['revision'])
        return row

    def create_project(self, command):
        def action(db):
            if command.expected_revision != 0:
                raise StoreError('invalid_input', 'Un nuovo progetto parte dalla revisione zero.', 422)
            project_id, scene_id = str(uuid4()), str(uuid4())
            self._insert_project(db, project_id, command.name.strip() or 'Nuovo progetto')
            db.execute('INSERT INTO scenes(id,project_id,number,title) VALUES (?,?,1,?)', (scene_id, project_id, 'Scena 1'))
            self._insert_cut(db, scene_id, empty_state(), 1, 'Cut 1')
            return self._project_view(db, self._entity(db, 'projects', project_id))
        return self._entity_command('create_project', 'projects', command, action)

    def create_scene(self, project_id, command):
        def action(db):
            self._entity(db, 'projects', project_id, command.expected_revision)
            number = db.execute('SELECT COALESCE(MAX(number),0)+1 FROM scenes WHERE project_id=?', (str(project_id),)).fetchone()[0]
            scene_id = str(uuid4())
            db.execute('INSERT INTO scenes(id,project_id,number,title) VALUES (?,?,?,?)', (scene_id, str(project_id), number, command.name.strip() or f'Scena {number}'))
            self._insert_cut(db, scene_id, empty_state(), 1, 'Cut 1')
            db.execute('UPDATE projects SET revision=revision+1,updated_at=? WHERE id=?', (now(), str(project_id)))
            return self._scene_view(db, self._entity(db, 'scenes', scene_id))
        return self._entity_command('create_scene', project_id, command, action)

    def create_cut(self, scene_id, command):
        def action(db):
            row = self._entity(db, 'scenes', scene_id, command.expected_revision)
            if row['finalized']:
                raise StoreError('scene_finalized', 'Riapri la scena prima di aggiungere un cut.')
            number = db.execute('SELECT COALESCE(MAX(number),0)+1 FROM cuts WHERE scene_id=?', (str(scene_id),)).fetchone()[0]
            state = empty_state()
            if command.inherit_references:
                previous = db.execute("""SELECT data FROM cuts WHERE scene_id=? AND COALESCE(json_extract(data,'$.trashed'),0)=0
                                         ORDER BY number DESC LIMIT 1""", (str(scene_id),)).fetchone()
                if previous:
                    self._inherit_cut_references(state, json.loads(previous['data']))
            self._insert_cut(db, str(scene_id), state, number, command.name.strip() or f'Cut {number}')
            db.execute('UPDATE scenes SET revision=revision+1 WHERE id=?', (str(scene_id),))
            return self._view(self._load(db, state['id']), db)
        return self._entity_command('create_cut', scene_id, command, action)

    @staticmethod
    def _inherit_cut_references(state, previous):
        draft = previous['draft_input']
        pictures = copy.deepcopy(draft.get('pictures') or [])
        units = copy.deepcopy(draft.get('active_units', []))
        for picture in pictures:
            picture['linked_to_h3'] = False
            if picture.pop('guidance', None) is not None:
                picture['confirmed'] = False
        for unit in units:
            sources = unit.get('sources')
            if isinstance(sources, list):
                kept = [source for source in sources if not isinstance(source, dict) or source.get('origin') != 'context']
                if len(kept) != len(sources):
                    unit.update(sources=kept, confirmed=False)
        state['draft_input'].update(pictures=pictures, active_units=units)
        picture_ids = {picture['id'] for picture in pictures}
        subjects = {str(unit['subject']) for unit in units}
        for keys, ids in ((('media_bindings', 'proxy_bindings', 'reference_revisions'), picture_ids),
                          (('unit_bindings', 'unit_revisions'), subjects)):
            for key in keys:
                state[key] = {id: value for id, value in previous.get(key, {}).items() if id in ids}

    def rename(self, table, id, command):
        if table == 'cuts':
            def action(state):
                self._transaction_db.execute('UPDATE cuts SET title=? WHERE id=?', (command.name.strip() or state['title'], str(id)))
                state['title'] = command.name.strip() or state['title']
            return self._command('rename_cut', id, command, action)[0]
        def action(db):
            row = self._entity(db, table, id, command.expected_revision)
            column = 'name' if table == 'projects' else 'title'
            db.execute(f'UPDATE {table} SET {column}=?,revision=revision+1 WHERE id=?', (command.name.strip() or row[column], str(id)))
            if table == 'projects':
                db.execute('UPDATE projects SET updated_at=? WHERE id=?', (now(), str(id)))
                return self._project_view(db, self._entity(db, table, id))
            return self._scene_view(db, self._entity(db, table, id))
        return self._entity_command(f'rename_{table}', id, command, action)

    def trash(self, table, id, command):
        def action(db):
            self._entity(db, table, id, command.expected_revision, active=False)
            # I job restano consultabili al ripristino; il cestino non cancella
            # file, versioni o input ed esclude soltanto nuove operazioni.
            db.execute(f'UPDATE {table} SET trashed=?,revision=revision+1 WHERE id=?', (int(command.trashed), str(id)))
            row = self._entity(db, table, id, active=False)
            return self._project_view(db, row) if table == 'projects' else self._scene_view(db, row)
        return self._entity_command(f'trash_{table}', id, command, action)

    def trash_cut(self, cut_id, command):
        def action(db):
            state = self._load(db, cut_id)
            scene = self._entity(db, 'scenes', state['scene_id'])
            if state['revision'] != command.expected_revision:
                raise StoreError('revision_conflict', 'Il cut è cambiato. Riapri «Gestisci nomi e cestino».',
                                 current_revision=state['revision'])
            if scene['finalized']:
                raise StoreError('scene_finalized', 'Riapri la scena prima di spostare o ripristinare un cut.')
            if bool(state.get('trashed')) == command.trashed:
                return self._scene_view(db, scene)
            if command.trashed:
                other_cut = db.execute("""SELECT 1 FROM cuts WHERE scene_id=? AND id<>?
                    AND COALESCE(json_extract(data,'$.trashed'),0)=0 LIMIT 1""", (scene['id'], state['id'])).fetchone()
                if not other_cut:
                    raise StoreError('last_cut', 'La scena deve avere almeno un cut attivo. Puoi spostare la scena nel cestino.')
                for table in ('jobs', 'assistance_jobs'):
                    if db.execute(f"SELECT 1 FROM {table} WHERE cut_id=? AND json_extract(data,'$.status') IN ('queued','running')",
                                  (state['id'],)).fetchone():
                        raise StoreError('cut_busy', 'Attendi che terminino i lavori di questo cut prima di spostarlo.')
            state.update(trashed=command.trashed, revision=state['revision'] + 1)
            self._write_cut(db, state)
            db.execute('UPDATE scenes SET revision=revision+1 WHERE id=?', (scene['id'],))
            return self._scene_view(db, self._entity(db, 'scenes', scene['id']))
        return self._entity_command('trash_cut', cut_id, command, action)

    def finalize(self, scene_id, command):
        def action(db):
            self._entity(db, 'scenes', scene_id, command.expected_revision)
            if command.finalized:
                cuts = [json.loads(r[0]) for r in db.execute(
                    "SELECT data FROM cuts WHERE scene_id=? AND COALESCE(json_extract(data,'$.trashed'),0)=0", (str(scene_id),))]
                if not cuts or any(not c.get('confirmed_version_id') or c['state'] != 'confirmed' for c in cuts):
                    raise StoreError('unconfirmed_cuts', 'Conferma la versione corrente di ogni cut prima di terminare la scena.')
                for cut in cuts:
                    version = json.loads(db.execute('SELECT data FROM versions WHERE id=?', (cut['confirmed_version_id'],)).fetchone()[0])
                    if self._confirmation_issues(db, version, verify_files=True):
                        raise StoreError('confirmation_blocked', 'Un cut confermato ha riferimenti non più disponibili. Ripristina i media prima di terminare la scena.', 422)
            db.execute('UPDATE scenes SET finalized=?,revision=revision+1 WHERE id=?', (int(command.finalized), str(scene_id)))
            return self._scene_view(db, self._entity(db, 'scenes', scene_id))
        return self._entity_command('finalize', scene_id, command, action)

    def confirm(self, cut_id, command):
        def action(state):
            db = self._transaction_db
            version = next((v for v in state['versions'] if v['id'] == str(command.version_id)), None)
            if version is None:
                raise StoreError('not_found', 'Versione non trovata in questo cut.', 404)
            issues = self._confirmation_issues(db, version, verify_files=True)
            if issues:
                raise StoreError('confirmation_blocked', ' '.join(issues), 422)
            base = next((v for v in state['versions'] if v['id'] == version.get('base_candidate_id')), None)
            snapshot = version['input_snapshot']
            def bindings(data):
                value = data or {}
                continuity = value.get('continuity') or {}
                return dict(pictures={p['slot']: p['id'] for p in value.get('pictures', [])},
                    excluded={f'{kind}:{item.get("id", item.get("subject"))}':True for kind in ['pictures','active_units'] for item in value.get(kind) or [] if item.get('excluded') is True},
                    subjects={u['subject']: [(s.get('origin', 'picture'), s.get('picture_id'), s.get('picture_slot'), s.get('attribute'))
                              for s in u.get('sources', []) if isinstance(s, dict)] for u in value.get('active_units', [])},
                    physical_details={u['subject']: self._unit_data(u)['physical_details'] for u in value.get('active_units', []) if u.get('physical_details')},
                    scales={u['subject']: u['scale'] for u in value.get('active_units', []) if u.get('scale')},
                    videos={v['slot']: v['id'] for v in value.get('videos', []) if v['id'] == continuity.get('video_id') or (v.get('guidance') or {}).get('enabled')},
                    guides={f'{kind}:{ref["id"]}':{'role':ref['role'],'usage':ref['guidance']} for kind in ['pictures','videos'] for ref in value.get(kind,[]) if (ref.get('guidance') or {}).get('enabled')},
                    context={k: continuity.get(k) for k in ['mode','previous_cut_id','previous_version_id','external_source','context_media_id','context_media_kind']})
            changed = bindings(snapshot) != bindings(state['draft_input'])
            identities = self._version_subject_ids(db, version['id'])
            same_identities = all(
                state.get('unit_bindings', {}).get(number) == identity
                for number, identity in identities.items()
            )
            changed |= not same_identities
            if base:
                base_identities = self._version_subject_ids(db, base['id'])
                changed |= any(
                    identities[number] != base_identities[number]
                    for number in identities.keys() & base_identities.keys()
                )
                changed |= (bindings(snapshot) != bindings(base.get('input_snapshot')) or
                            version.get('media_snapshot', {}) != base.get('media_snapshot', {}))
            changed |= version.get('media_snapshot', {}) != self._media_snapshot(db, snapshot, state)
            if changed and not command.acknowledge_reference_changes:
                raise StoreError('reference_reconciliation_required', 'Le associazioni dei riferimenti sono cambiate. Rivedi lo snapshot della versione e conferma esplicitamente i riferimenti da usare.')
            db.execute('INSERT INTO approvals VALUES (?,?,?,?)', (str(uuid4()), state['id'], version['id'], now()))
            state['confirmed_version_id'] = version['id']
            # La conferma di una versione precedente non elimina la bozza nuova.
            try:
                same = (same_identities and CompileInput.model_validate(state['draft_input']) == CompileInput.model_validate(snapshot) and
                        version.get('media_snapshot', {}) == self._media_snapshot(db, state['draft_input'], state))
            except Exception:
                same = False
            state['state'] = 'confirmed' if same else 'draft'
        return self._command('confirm', cut_id, command, action)[0]

    def library(self, project_id, scene_id=None):
        with closing(self.connect()) as db:
            project = self._entity(db, 'projects', project_id)
            trashed = self._library_trashed(db, project_id)
            if scene_id and self._entity(db,'scenes',scene_id)['project_id'] != str(project_id):
                raise StoreError('not_found','Scena non appartenente al progetto.',404)
            references = []
            for row in db.execute('SELECT * FROM project_references WHERE project_id=? ORDER BY rowid', (str(project_id),)):
                media = db.execute('SELECT * FROM media WHERE id=?', (row['media_id'],)).fetchone() if row['media_id'] else None
                references.append({'id': row['id'], **json.loads(row['data']), 'revision': row['revision'],
                                   'media': self.media_view(media) if media else None})
            units = [{'id': row['id'], **json.loads(row['data']), 'revision': row['revision']} for row in
                     db.execute('SELECT * FROM project_units WHERE project_id=? ORDER BY subject', (str(project_id),))]
            if scene_id:
                numbers = {r['unit_id']:r['subject'] for r in db.execute('SELECT * FROM scene_subjects WHERE scene_id=?',(str(scene_id),))}
                for unit in units:unit['subject'] = numbers.get(unit['id'])
            return {'pictures': [r for r in references if ('picture',r['id']) not in trashed],
                    'units': [u for u in units if ('unit',u['id']) not in trashed],
                    'trashed_pictures': [r for r in references if ('picture',r['id']) in trashed],
                    'trashed_units': [u for u in units if ('unit',u['id']) in trashed],
                    'revision': project['revision'], 'camera_presets': self._camera_presets(db, project_id)}

    def reuse(self, cut_id, command):
        def action(state):
            db = self._transaction_db
            data = state['draft_input']
            required = []
            unit = None
            self._check_library_reuse(db, state['project_id'], command.kind, command.reference_id)
            if command.kind == 'picture':
                required.append(str(command.reference_id))
            else:
                row = db.execute('SELECT * FROM project_units WHERE id=? AND project_id=?', (str(command.reference_id), state['project_id'])).fetchone()
                if row is None:
                    raise StoreError('not_found', 'Subject non trovato nel progetto.', 404)
                unit = json.loads(row['data'])
                for picture_id in unit_picture_ids(unit):
                    self._check_library_reuse(db, state['project_id'], 'picture', picture_id)
                unit['subject'] = self._assign_scene_unit(db,state,row['id'])
                resolve_scale_subject(unit, {r['unit_id']: r['subject'] for r in db.execute('SELECT * FROM scene_subjects WHERE scene_id=?', (state['scene_id'],))})
                required = unit_picture_ids(unit)
                state.setdefault('unit_revisions', {})[str(unit['subject'])] = row['revision']
                state.setdefault('unit_bindings', {})[str(unit['subject'])] = row['id']
            existing = {p['id']: p for p in data.get('pictures', [])}
            used = {p['slot'] for p in existing.values()}
            for id in required:
                if id in existing and command.kind == 'unit':
                    continue
                slot = existing[id]['slot'] if id in existing else command.slots.get(id)
                if type(slot) is not int or slot not in range(1, 10) or (id not in existing and slot in used):
                    raise StoreError('invalid_input', 'Assegna esplicitamente uno slot libero da 1 a 9 a ciascuna immagine da riusare.', 422)
                row = db.execute('SELECT * FROM project_references WHERE id=? AND project_id=?', (id, state['project_id'])).fetchone()
                if row is None:
                    raise StoreError('not_found', 'Immagine non trovata nel progetto.', 404)
                picture = {'id': id, **json.loads(row['data']), 'slot': slot, 'linked_to_h3': False}
                if id in existing:
                    if existing[id].get('excluded'): picture['excluded'] = True
                    # Ricaricare file/descrizione non deve perdere il mapping
                    # locale del cut, che non fa parte del catalogo canonico.
                    if picture['role'] == existing[id].get('role') and existing[id].get('guidance') is not None:
                        picture['guidance'] = copy.deepcopy(existing[id]['guidance'])
                        picture['confirmed'] = False
                    data['pictures'][data['pictures'].index(existing[id])] = picture
                    for active in data.get('active_units', []):
                        if id in unit_picture_ids(active):
                            active['confirmed'] = False
                else:
                    data.setdefault('pictures', []).append(picture)
                media = db.execute('SELECT id,sha256 FROM media WHERE id=?', (row['media_id'],)).fetchone() if row['media_id'] else None
                if media:
                    state.setdefault('media_bindings', {})[id] = dict(media)
                else:
                    state.setdefault('media_bindings', {}).pop(id, None)
                proxy = db.execute('SELECT m.id,m.sha256 FROM media m JOIN reference_proxies p ON p.media_id=m.id WHERE p.reference_id=?', (id,)).fetchone()
                if proxy: state.setdefault('proxy_bindings', {})[id] = dict(proxy)
                else: state.setdefault('proxy_bindings', {}).pop(id, None)
                state.setdefault('reference_revisions', {})[id] = row['revision']
                used.add(slot)
            if unit:
                found = next((u for u in data.get('active_units', []) if u['subject'] == unit['subject']), None)
                if found:
                    if found.get('excluded'): unit['excluded'] = True
                    data['active_units'][data['active_units'].index(found)] = copy.deepcopy(unit)
                else:
                    data.setdefault('active_units', []).append(copy.deepcopy(unit))
            state['state'] = 'draft'
        return self._command('reuse', cut_id, command, action)[0]

    def attach_media(self, cut_id, picture_id, command):
        def action(state):
            db = self._transaction_db
            if not any(p['id'] == str(picture_id) for p in state['draft_input'].get('pictures', [])):
                raise StoreError('not_found', 'Immagine non presente nel cut.', 404)
            media = db.execute('SELECT id,sha256 FROM media WHERE id=?', (str(command.media_id),)).fetchone()
            if not media:
                raise StoreError('not_found', 'Media non trovato.', 404)
            row = db.execute('SELECT revision FROM project_references WHERE id=? AND project_id=?', (str(picture_id), state['project_id'])).fetchone()
            if state.get('reference_revisions', {}).get(str(picture_id)) != row['revision']:
                raise StoreError('reference_conflict', 'Il riferimento è cambiato. Ricaricalo prima di sostituire il file.')
            db.execute('UPDATE project_references SET media_id=?,revision=revision+1 WHERE id=?', (str(command.media_id), str(picture_id)))
            state.setdefault('reference_revisions', {})[str(picture_id)] = row['revision'] + 1
            state.setdefault('media_bindings', {})[str(picture_id)] = dict(media)
            for picture in state['draft_input']['pictures']:
                if picture['id'] == str(picture_id):
                    picture['confirmed'] = False
                    picture['linked_to_h3'] = False
            state['state'] = 'draft'
        return self._command(f'attach_media:{picture_id}', cut_id, command, action)[0]

    def cancel_job(self, job_id, command):
        with closing(self.connect()) as db:
            row = db.execute('SELECT cut_id FROM jobs WHERE id=?', (str(job_id),)).fetchone()
            if row is None:
                raise StoreError('not_found', 'Lavoro non trovato.', 404)
            cut_id = row['cut_id']
        def action(state):
            job = state['jobs'][str(job_id)]
            if job['status'] not in {'queued', 'running'}:
                raise StoreError('job_finished', 'Il lavoro è già terminato. La versione resta consultabile.')
            job['status'] = 'cancelled'
            job['result'] = CompileResult(status='error', input_hash=job['input_hash'], error_code='cancelled',
                issues=['Proposta annullata. Un’inferenza già iniziata termina in coda ma il suo risultato non verrà applicato.']).model_dump(mode='json')
            state['state'] = 'draft'
        return self._command(f'cancel:{job_id}', cut_id, command, action)[0]
