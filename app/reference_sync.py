"""Synchronize shared descriptions within an open scene; never rewrite versions."""
import copy
import json

from app.physical import unit_picture_ids
from app.scale import resolve_scale_subject


PICTURE_FIELDS = frozenset({'name', 'description_en', 'description_language',
                           'use_original_language', 'original_description', 'original_language'})
UNIT_FIELDS = frozenset({'name', 'description_en', 'definition_mode', 'physical_details', 'scale'})


def synchronize_scene_descriptions(repository, db, scene_id, *, apply=True):
    scene = db.execute('SELECT finalized,project_id FROM scenes WHERE id=?', (scene_id,)).fetchone()
    if not scene or scene['finalized']:
        return
    # Only draft metadata is needed. Do not load (or rewrite) historical
    # versions, jobs or media blobs while refreshing a scene.
    states = [dict(json.loads(row['data']), id=row['id'], scene_id=scene_id, project_id=scene['project_id'])
              for row in db.execute('SELECT id,data FROM cuts WHERE scene_id=?', (scene_id,))]
    states = [state for state in states if not state.get('trashed')]
    if not states:
        return
    dirty = set()
    bindings = {row['subject']: row['unit_id'] for row in
                db.execute('SELECT subject,unit_id FROM scene_subjects WHERE scene_id=?', (scene_id,))}
    for key, table, revision_key, fields in [
        ('pictures', 'project_references', 'reference_revisions', PICTURE_FIELDS),
        ('active_units', 'project_units', 'unit_revisions', UNIT_FIELDS),
    ]:
        for row in db.execute(f'SELECT * FROM {table} WHERE project_id=?', (states[0]['project_id'],)):
            canonical = json.loads(row['data'])
            canonical = (repository._reference_data(canonical) if key == 'pictures'
                         else repository._unit_data(canonical))
            uses = []
            for state in states:
                for item in state['draft_input'].get(key, []):
                    number = str(item.get('subject'))
                    if key == 'pictures':
                        if item['id'] != row['id']:
                            continue
                        media = (state.get('media_bindings', {}).get(item['id']) or {}).get('id')
                        proxy = (state.get('proxy_bindings', {}).get(item['id']) or {}).get('id')
                        current_proxy = db.execute('SELECT media_id FROM reference_proxies WHERE reference_id=?',
                                                   (item['id'],)).fetchone()
                        # Text for a newer image must not be applied to an older file.
                        if media != row['media_id'] or proxy != (current_proxy[0] if current_proxy else None):
                            continue
                        identity = item['id']
                        value = repository._reference_data(item)
                    else:
                        if bindings.get(item['subject']) != row['id']:
                            continue
                        if state.get('unit_bindings', {}).get(number, row['id']) != row['id']:
                            continue
                        # A definition explicitly taken from a historical continuity
                        # version remains that version's definition.
                        sources = item.get('sources', [])
                        if not isinstance(sources, list) or any(not isinstance(s, dict) for s in sources):
                            continue  # Incomplete draft fields remain saveable as entered.
                        if any(s.get('origin') == 'context' for s in sources):
                            continue
                        identity = number
                        value = repository._unit_data(item)
                        value['subject'] = row['subject']
                    uses.append((state, item, identity, value))
            # Also repairs old stale drafts, but only when a cut of THIS scene
            # demonstrably owns the current library content/revision.
            if not any(state.get(revision_key, {}).get(identity) == row['revision'] and value == canonical
                       for state, _, identity, value in uses):
                continue
            for state, item, identity, value in uses:
                if state.get(revision_key, {}).get(identity) == row['revision']:
                    continue
                structural = set(value) | set(canonical)
                if any(value.get(field) != canonical.get(field)
                       for field in structural - fields - {'confirmed'}):
                    continue
                if key == 'active_units':
                    picture_ids = {p['id'] for p in state['draft_input'].get('pictures', [])}
                    if not set(unit_picture_ids(canonical)).issubset(picture_ids):
                        continue
                before = copy.deepcopy(item)
                for field in fields:
                    if field in canonical:
                        item[field] = copy.deepcopy(canonical[field])
                    else:
                        item.pop(field, None)
                # Synchronization never grants a confirmation the target cut lacked.
                if not canonical.get('confirmed'):
                    item['confirmed'] = False
                state.setdefault(revision_key, {})[identity] = row['revision']
                dirty.add(state['id'])
                if before != item:
                    state['state'] = 'draft'
    if not apply:
        return bool(dirty)
    for state in states:
        if state['id'] not in dirty:
            continue
        numbers = {row['unit_id']: row['subject'] for row in
                   db.execute('SELECT * FROM scene_subjects WHERE scene_id=?', (scene_id,))}
        for unit in state['draft_input'].get('active_units', []):
            resolve_scale_subject(unit, numbers)
        state['revision'] += 1
        repository._write_cut(db, state)
    return bool(dirty)
