"""Numeri Subject locali alla scena, separati dall'identità della libreria."""
import copy
import json
import re

from app.store import StoreError


def draft_subject_numbers(data):
    """Numeri usati dalle unità e dai riferimenti della bozza corrente."""
    numbers = set()

    def add_number(number):
        if type(number) is int and number > 0:
            numbers.add(number)

    def add_text(text):
        if isinstance(text, str):
            numbers.update(int(n) for n in re.findall(r'<Subject ([1-9][0-9]*)>', text))

    def items(parent, key):
        values = parent.get(key)
        return [value for value in values if isinstance(value, dict)] if isinstance(values, list) else []

    for unit in items(data, 'active_units'):
        add_number(unit.get('subject'))
        if isinstance(unit.get('scale'), dict):add_number(unit['scale'].get('reference_subject'))
    for item in [*items(data, 'dialogues'), *items(data, 'audio_references')]:
        add_number(item.get('speaker_subject'))
    add_text(data.get('request'))
    add_text(data.get('soundscape_text'))
    continuity = data.get('continuity')
    if isinstance(continuity, dict):
        add_text(continuity.get('declared_state'))
    camera = data.get('camera')
    if isinstance(camera, dict):
        add_number(camera.get('subject'))
        add_text(camera.get('notes'))
    for reference in [*items(data, 'pictures'), *items(data, 'videos')]:
        guide = reference.get('guidance')
        if isinstance(guide, dict):
            add_text(guide.get('prompt_en'))
            for mapping in items(guide, 'mappings'):
                add_number(mapping.get('subject'))
    return numbers


def remap_subjects(data, mapping):
    """Riallinea riferimenti della bozza, mai parole di dialoghi o trascrizioni."""
    result = copy.deepcopy(data)
    def token(text):
        return re.sub(r'<Subject ([1-9][0-9]*)>', lambda m: f'<Subject {mapping.get(int(m[1]), int(m[1]))}>', text)
    for unit in result.get('active_units', []):
        unit['subject'] = mapping.get(unit['subject'], unit['subject'])
        scale = unit.get('scale')
        if isinstance(scale, dict) and scale.get('reference_subject') in mapping:
            scale['reference_subject'] = mapping[scale['reference_subject']]
    for item in [*result.get('dialogues', []), *result.get('audio_references', [])]:
        if item.get('speaker_subject') in mapping:item['speaker_subject'] = mapping[item['speaker_subject']]
    if result.get('camera'):
        camera = result['camera']
        if camera.get('subject') in mapping:camera['subject'] = mapping[camera['subject']]
        if camera.get('notes'):camera['notes'] = token(camera['notes'])
    for ref in [*result.get('pictures', []), *result.get('videos', [])]:
        guide = ref.get('guidance') or {}
        for item in guide.get('mappings', []):
            if item.get('subject') in mapping:item['subject'] = mapping[item['subject']]
        if guide.get('prompt_en'):guide['prompt_en'] = token(guide['prompt_en'])
    for container, key in [(result, 'request'), (result, 'soundscape_text'), (result.get('continuity') or {}, 'declared_state')]:
        if container.get(key):container[key] = token(container[key])
    return result


class SubjectOperations:
    def _initialize_scene_subjects(self, db):
        # Migrazione additiva: conserva numeri e contenuti esistenti. La
        # compattazione di una scena è un comando esplicito separato.
        for row in db.execute('SELECT c.data,c.scene_id,s.project_id FROM cuts c JOIN scenes s ON s.id=c.scene_id ORDER BY c.rowid').fetchall():
            state = json.loads(row['data'])
            for unit in state.get('draft_input', {}).get('active_units', []):
                identity = state.get('unit_bindings', {}).get(str(unit['subject']))
                source = db.execute('SELECT id FROM project_units WHERE project_id=? AND '+('id=?' if identity else 'subject=?'),
                                    (row['project_id'], identity or unit['subject'])).fetchone()
                if source:
                    db.execute('INSERT OR IGNORE INTO scene_subjects VALUES (?,?,?)', (row['scene_id'],unit['subject'],source['id']))
                    actual = self._scene_unit(db,row['scene_id'],unit['subject'])
                    if not actual or actual['id'] != source['id']:
                        raise RuntimeError('Numerazione della scena ambigua: migrazione annullata, backup conservato.')
        for row in db.execute('SELECT v.id,v.data,s.project_id FROM versions v JOIN cuts c ON c.id=v.cut_id JOIN scenes s ON s.id=c.scene_id').fetchall():
            for unit in (json.loads(row['data']).get('input_snapshot') or {}).get('active_units', []):
                source = db.execute('SELECT id FROM project_units WHERE project_id=? AND subject=?', (row['project_id'],unit['subject'])).fetchone()
                if source:db.execute('INSERT OR IGNORE INTO version_subjects VALUES (?,?,?)', (row['id'],unit['subject'],source['id']))

    def _scene_unit(self, db, scene_id, number):
        return db.execute('SELECT u.* FROM project_units u JOIN scene_subjects b ON b.unit_id=u.id WHERE b.scene_id=? AND b.subject=?', (scene_id, number)).fetchone()

    def _assign_scene_unit(self, db, state, identity):
        row = db.execute('SELECT subject FROM scene_subjects WHERE scene_id=? AND unit_id=?', (state['scene_id'],identity)).fetchone()
        if row:return row[0]
        number = self._available_subject(state)
        db.execute('INSERT INTO scene_subjects VALUES (?,?,?)', (state['scene_id'], number, identity))
        state['subject_numbers'].append(number)
        return number

    def _version_subject_ids(self, db, version_id):
        return {str(row['subject']):row['unit_id'] for row in db.execute('SELECT subject,unit_id FROM version_subjects WHERE version_id=?', (version_id,))}

    def compact_scene_subjects(self, scene_id, command):
        def action(db):
            scene = self._entity(db, 'scenes', scene_id, command.expected_revision)
            if scene['finalized']:raise StoreError('scene_finalized', 'Riapri la scena prima di rinumerare i Subject.')
            for table in ['jobs','assistance_jobs']:
                if any(json.loads(r[0])['status'] in {'queued','running'} for r in db.execute('SELECT data FROM '+table)):
                    raise StoreError('subjects_busy', 'Attendi il termine dei lavori prima di rinumerare i Subject.')
            cuts = [self._load(db,r[0]) for r in db.execute('SELECT id FROM cuts WHERE scene_id=? ORDER BY number', (str(scene_id),)).fetchall()]
            active = sorted({u['subject'] for c in cuts for u in c['draft_input'].get('active_units', [])})
            mapping = {n:i+1 for i,n in enumerate(active)}
            bindings = {}
            for n in active:
                row = self._scene_unit(db,str(scene_id),n)
                if not row:raise StoreError('unknown_subject_identity','Un Subject della bozza non ha un’identità verificabile.',422)
                bindings[n] = row['id']
            # Un richiamo rimasto senza unità non può diventare per coincidenza
            # il nuovo numero di un'altra identità.
            targets = set(mapping.values())-set(active)
            for cut in cuts:
                if draft_subject_numbers(cut['draft_input']) & targets:
                    raise StoreError('subject_references_unresolved','Correggi i richiami a Subject assenti prima di rinumerare la scena.',422)
            if any(n != target for n,target in mapping.items()):
                db.execute('DELETE FROM scene_subjects WHERE scene_id=?', (str(scene_id),))
                for n,target in mapping.items():db.execute('INSERT INTO scene_subjects VALUES (?,?,?)', (str(scene_id),target,bindings[n]))
                for state in cuts:
                    updated = remap_subjects(state['draft_input'],mapping)
                    if updated != state['draft_input']:
                        state['draft_input'] = updated
                        state['unit_bindings'] = {str(mapping[int(n)]):identity for n,identity in state.get('unit_bindings',{}).items() if int(n) in mapping}
                        state['unit_revisions'] = {str(mapping[int(n)]):v for n,v in state.get('unit_revisions',{}).items() if int(n) in mapping}
                        state['revision'] += 1;state['state'] = 'draft'
                        self._write_cut(db,state)
                db.execute('UPDATE scenes SET revision=revision+1 WHERE id=?', (str(scene_id),))
            return self._scene_view(db,self._entity(db,'scenes',scene_id))
        return self._entity_command('compact_scene_subjects',scene_id,command,action)
