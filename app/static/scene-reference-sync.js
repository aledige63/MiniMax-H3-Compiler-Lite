import {unitPictureIds} from './reference-menu.js';

const pictureFields = new Set(['name', 'description_en', 'description_language',
  'use_original_language', 'original_description', 'original_language', 'confirmed']);
const unitFields = new Set(['name', 'description_en', 'definition_mode', 'physical_details', 'scale', 'confirmed']);
const stable = value => Array.isArray(value) ? value.map(stable) : value && typeof value === 'object'
  ? Object.fromEntries(Object.keys(value).sort().map(key => [key, stable(value[key])])) : value;
export const sameReferenceValue = (a, b) => JSON.stringify(stable(a)) === JSON.stringify(stable(b));

// Only descriptive reference changes can be rebased automatically. Requests,
// dialogue, membership, slots, mappings and other edits still require recovery.
export function mergeSceneReferences(base, local, remote, ignored = null) {
  const merged = structuredClone(local);
  for (const key of new Set([...Object.keys(base), ...Object.keys(remote)])) {
    if (key !== 'pictures' && key !== 'active_units' && !sameReferenceValue(base[key], remote[key])) return null;
  }
  for (const [key, identity, fields] of [['pictures', 'id', pictureFields], ['active_units', 'subject', unitFields]]) {
    const before = base[key] || [], after = remote[key] || [];
    if (!sameReferenceValue(before.map(item => item[identity]), after.map(item => item[identity]))) return null;
    for (const current of after) {
      const old = before.find(item => item[identity] === current[identity]);
      const target = (merged[key] || []).find(item => item[identity] === current[identity]);
      for (const field of new Set([...Object.keys(old), ...Object.keys(current)])) {
        if (sameReferenceValue(old[field], current[field])) continue;
        if (!fields.has(field)) return null;
        if (!target || (ignored?.key === key && ignored.id === current[identity])) continue;
        if (!sameReferenceValue(target[field], old[field]) && !sameReferenceValue(target[field], current[field])) return null;
        if (Object.hasOwn(current, field)) target[field] = structuredClone(current[field]);
        else delete target[field];
      }
    }
  }
  return merged;
}

// Explicit library reload replaces only the chosen reference. Unrelated local
// fields, including text that has not been saved yet, remain in the editor.
export function applyLibraryReference(local, server, kind, referenceId, unitIds, slots = {}) {
  const merged = structuredClone(local);
  let selected;
  if (kind === 'unit') {
    const number = Object.entries(unitIds).find(([, id]) => id === referenceId)?.[0];
    selected = server.active_units.find(unit => String(unit.subject) === number);
    if (!selected) throw new Error('Subject non disponibile nella risposta della libreria.');
    const old = merged.active_units.find(unit => unit.subject === selected.subject);
    const value = structuredClone(selected);
    if (old?.excluded) value.excluded = true;
    else delete value.excluded;
    if (old) merged.active_units[merged.active_units.indexOf(old)] = value;
    else merged.active_units.push(value);
  }
  const ids = kind === 'picture' ? [referenceId] : unitPictureIds(selected);
  for (const id of ids) {
    const old = merged.pictures.find(picture => picture.id === id);
    if (old && kind === 'unit') continue;
    const current = server.pictures.find(picture => picture.id === id);
    if (!current) throw new Error('Immagine non disponibile nella risposta della libreria.');
    const value = structuredClone(current);
    value.slot = old?.slot ?? slots[id] ?? value.slot;
    if (old) {
      if (old.excluded) value.excluded = true;
      else delete value.excluded;
      if (old.role === value.role && old.guidance !== undefined) value.guidance = structuredClone(old.guidance);
      merged.pictures[merged.pictures.indexOf(old)] = value;
    } else merged.pictures.push(value);
  }
  return merged;
}
