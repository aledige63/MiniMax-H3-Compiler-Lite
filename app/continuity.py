"""Raccordi e risultati versionati: metadati espliciti, nessuna inferenza."""
import copy
import json

from app.store import StoreError
from app.domain import resolved_definition
from app.video import VideoStore
from app.scale import resolve_scale_subject


class ContinuityOperations:
    def _check_continuity_links(self, db, state, data):
        continuity = data.get('continuity') or {}
        previous = continuity.get('previous_cut_id')
        if previous:
            row = db.execute('SELECT * FROM cuts WHERE id=? AND scene_id=? AND number<?',
                             (previous, state['scene_id'], state['number'])).fetchone()
            if row is None: raise StoreError('invalid_input', 'La continuità può provenire soltanto da un cut precedente della stessa scena.', 422)
        version = continuity.get('previous_version_id')
        if version and not db.execute('SELECT 1 FROM versions WHERE id=? AND cut_id=?', (version, previous)).fetchone():
            raise StoreError('invalid_input', 'La versione di origine non appartiene al cut precedente scelto.', 422)
        context_id = continuity.get('context_media_id')
        if context_id:
            table = 'video_media' if continuity.get('context_media_kind') == 'video' else 'media' if continuity.get('context_media_kind') == 'image' else None
            if not table or not db.execute(f'SELECT 1 FROM {table} WHERE id=?', (context_id,)).fetchone():
                raise StoreError('invalid_input', 'Il media di contesto deve esistere nell’archivio gestito.', 422)
        videos = data.get('videos', [])
        if not isinstance(videos, list) or any(not isinstance(v, dict) or v.get('id') not in state.get('video_ids', []) for v in videos):
            raise StoreError('invalid_input', 'Usa i riferimenti Video assegnati dal server.', 422)
        for video in videos:
            if video.get('media_id'):
                row = db.execute('SELECT data FROM video_media WHERE id=?', (video['media_id'],)).fetchone()
                if row is None or video.get('duration_origin') != 'measured' or video.get('duration_s') != json.loads(row[0])['duration_s']:
                    raise StoreError('invalid_input', 'La durata del Video gestito deve corrispondere al file decodificato.', 422)
            elif video.get('duration_origin') == 'measured':
                raise StoreError('invalid_input', 'Senza file locale la durata Video è soltanto dichiarata.', 422)

    def add_video_item(self, cut_id, command):
        def action(state):
            videos = state['draft_input'].setdefault('videos', [])
            used = {v.get('slot') for v in videos}
            slot = next((n for n in range(1, 4) if n not in used), None)
            if slot is None: raise StoreError('invalid_input', 'Il cut ammette fino a tre slot Video.', 422)
            n = state.get('next_video', 1); state['next_video'] = n + 1
            id = f'v{n}'; state.setdefault('video_ids', []).append(id)
            videos.append(dict(id=id, slot=slot, name='', role='continuation', description_en='the source clip for continuation',
                media_id=None, duration_s=None, duration_origin='declared', file_exists=False, linked_to_h3=False, confirmed=False))
            state['state'] = 'draft'
        return self._command('item', cut_id, command, action)[0]

    def attach_video(self, cut_id, video_id, command):
        def action(state):
            db = self._transaction_db
            row = db.execute('SELECT * FROM video_media WHERE id=?', (str(command.media_id),)).fetchone()
            video = next((v for v in state['draft_input'].get('videos', []) if v['id'] == video_id), None)
            if row is None or video is None: raise StoreError('not_found', 'Video o slot non trovato.', 404)
            meta = VideoStore.view(row)
            video.update(media_id=meta['id'], name=video.get('name') or meta['display_name'], duration_s=meta['duration_s'],
                         duration_origin='measured', file_exists=True, confirmed=False, linked_to_h3=False)
            state['state'] = 'draft'
        return self._command(f'attach_video:{video_id}', cut_id, command, action)[0]

    def attach_output(self, cut_id, command):
        def action(state):
            db = self._transaction_db
            if not db.execute('SELECT 1 FROM versions WHERE id=? AND cut_id=?', (str(command.version_id), str(cut_id))).fetchone():
                raise StoreError('not_found', 'Scegli una versione del prompt di questo cut prima di associare il risultato.', 404)
            if not db.execute('SELECT 1 FROM video_media WHERE id=?', (str(command.media_id),)).fetchone():
                raise StoreError('not_found', 'Video generato non trovato.', 404)
            db.execute('INSERT INTO cut_outputs VALUES (?,?,?) ON CONFLICT(cut_id,version_id) DO UPDATE SET media_id=excluded.media_id',
                       (str(cut_id), str(command.version_id), str(command.media_id)))
        return self._command('attach_output', cut_id, command, action, allow_finalized=True)[0]

    def _previous_cut(self, db, state):
        continuity = state['draft_input'].get('continuity') or {}
        source = continuity.get('previous_cut_id')
        filter_source = 'id=?' if source else "COALESCE(json_extract(data,'$.trashed'),0)=0"
        row = db.execute('SELECT id FROM cuts WHERE scene_id=? AND number<? AND ' + filter_source + ' ORDER BY number DESC LIMIT 1',
                         (state['scene_id'], state['number'], source) if source else (state['scene_id'], state['number'])).fetchone()
        return self._load(db, row['id']) if row else None

    def _previous_view(self, db, state):
        previous = self._previous_cut(db, state)
        if previous is None: return None
        explicit = (state['draft_input'].get('continuity') or {}).get('previous_version_id')
        selected = explicit or previous.get('confirmed_version_id') or (previous['versions'][-1]['id'] if previous['versions'] else None)
        version = next((v for v in previous['versions'] if v['id'] == selected), None)
        snapshot = version.get('input_snapshot') if version else previous['draft_input']
        output = db.execute('SELECT v.* FROM video_media v JOIN cut_outputs o ON o.media_id=v.id WHERE o.cut_id=? AND o.version_id=?',
                            (previous['id'], selected)).fetchone() if selected else None
        units = copy.deepcopy([u for u in (snapshot or {}).get('active_units', []) if not u.get('excluded')])
        identities = self._version_subject_ids(db,selected) if version else previous.get('unit_bindings',{})
        for unit in units:
            identity = identities.get(str(unit['subject']))
            target = db.execute('SELECT subject FROM scene_subjects WHERE scene_id=? AND unit_id=?',(state['scene_id'],identity)).fetchone() if identity else None
            unit['project_unit_id'] = identity
            unit['local_subject'] = target[0] if target else None
        return dict(id=previous['id'], number=previous['number'], title=previous['title'], state=previous['state'],
                    confirmed_version_id=previous.get('confirmed_version_id'), version=version,
                    versions=[{k: v.get(k) for k in ['id','origin','duration_s','duration_origin']} for v in previous['versions']],
                    units=units, snapshot_known=snapshot is not None,
                    output=VideoStore.view(output) if output else None)

    def continuity_view(self, db, state):
        videos = {}
        for video in state['draft_input'].get('videos', []):
            row = db.execute('SELECT * FROM video_media WHERE id=?', (video.get('media_id'),)).fetchone()
            if row: videos[video['id']] = VideoStore.view(row)
        context = state['draft_input'].get('continuity') or {}
        context_media = None
        if context.get('context_media_id'):
            table = 'video_media' if context.get('context_media_kind') == 'video' else 'media'
            row = db.execute(f'SELECT * FROM {table} WHERE id=?', (context['context_media_id'],)).fetchone()
            if row: context_media = (VideoStore.view(row) if table == 'video_media' else self.media_view(row)) | {'kind': context['context_media_kind']}
        outputs = {r['version_id']: VideoStore.view(r) for r in db.execute(
            'SELECT v.*,o.version_id FROM cut_outputs o JOIN video_media v ON v.id=o.media_id WHERE o.cut_id=?', (state['id'],))}
        return dict(video_media=videos, context_media=context_media, output_by_version=outputs, previous_cut=self._previous_view(db, state))

    def reuse_context_subject(self, cut_id, command):
        def action(state):
            db = self._transaction_db
            context = state['draft_input'].get('continuity') or {}
            if context.get('mode', 'none') == 'none' or not context.get('previous_cut_id') or not context.get('previous_version_id'):
                raise StoreError('invalid_input', 'Scegli prima una modalità e il cut precedente come sorgente.', 422)
            self._check_continuity_links(db, state, state['draft_input'])
            previous = self._previous_view(db, state)
            unit = next((u for u in previous['units'] if u['subject'] == command.subject), None) if previous else None
            if unit is None: raise StoreError('not_found', 'Subject non presente nello snapshot del cut precedente.', 404)
            identity = unit.get('project_unit_id')
            if not identity:raise StoreError('unknown_subject_identity','Identità storica non verificabile: riprendi il Subject dalla libreria.',422)
            number = self._assign_scene_unit(db,state,identity)
            if any(u['subject'] == number for u in state['draft_input'].get('active_units', [])):
                raise StoreError('invalid_input', 'Subject già presente nel cut: modifica esplicitamente le sue sorgenti.', 422)
            unit = copy.deepcopy(unit)
            unit.pop('project_unit_id',None);unit.pop('local_subject',None);unit['subject'] = number
            resolve_scale_subject(unit, {r['unit_id']: r['subject'] for r in db.execute('SELECT * FROM scene_subjects WHERE scene_id=?', (state['scene_id'],))})
            state.setdefault('unit_bindings',{})[str(number)] = identity
            state.setdefault('unit_revisions',{})[str(number)] = self._scene_unit(db,state['scene_id'],number)['revision']
            # Le versioni storiche usavano la definizione manuale del Subject.
            # Le nuove conservano la scelta di provenienza nello snapshot.
            if 'definition_mode' in unit:
                unit['description_en'] = resolved_definition(unit, (previous['version'].get('input_snapshot') or {}).get('pictures'))
            unit['definition_mode'] = 'manual'
            attrs = list(dict.fromkeys(s['attribute'] for s in unit.get('sources', [])))
            unit['sources'] = [dict(origin='context', attribute=a, picture_id=None, picture_slot=None, linked_to_h3=False) for a in attrs]
            for detail in unit.get('physical_details', []):
                detail.update(origin='context', picture_id=None)
            unit['confirmed'] = False
            state['draft_input'].setdefault('active_units', []).append(unit)
            state['state'] = 'draft'
        return self._command('reuse_context_subject', cut_id, command, action)[0]
