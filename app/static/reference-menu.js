import { t, tr } from "./i18n.js";

// I token e gli ID provengono dal server; la vista rispecchia gli edit locali.
export const imageGuideRoles = new Set(['style','spatial_map','composition_previz','initial_composition','frame_anchor']);
export function unitPictureIds(unit) {
  return [...new Set([...(unit.sources || []), ...(unit.physical_details || []), unit.scale || {}].map(item => item.picture_id).filter(Boolean))];
}
export function definitionPicture(unit, pictures) {
  const attribute = {character:"identity",environment:"environment",object:"object"}[unit.role];
  const sources = unit.sources || [];
  const source = sources.find(s=>s.attribute === attribute) || sources.find(s=>s.attribute === "appearance");
  if (!source || source.origin === "context") return null;
  return (pictures || []).find(p=>p.id === source.picture_id) || null;
}

export function subjectDefinition(unit, pictures) {
  const picture = unit.definition_mode !== "manual" ? definitionPicture(unit, pictures) : null;
  return (picture ? picture.description_en || "" : unit.description_en || "").trim();
}

export function visibleReferenceTokens(tokens, draft) {
  return tokens.flatMap(candidate => {
    if (candidate.kind === "unit") return draft.active_units.some(u => !u.excluded && String(u.subject) === candidate.id) ? [candidate] : [];
    if (candidate.kind === "dialogue") return draft.dialogues.some(d => d.id === candidate.id) ? [candidate] : [];
    if (candidate.kind === "audio") return (draft.audio_references || []).some(a => a.id === candidate.id && candidate.token === `<Audio ${a.slot}>` && a.media_id && a.confirmed && a.linked_to_h3) ? [candidate] : [];
    if (candidate.kind === "video") return (draft.videos || []).some(v => v.id === candidate.id && candidate.token === `<Video ${v.slot}>` && (draft.continuity?.mode === "video_reference" && draft.continuity.video_id === v.id || ['camera','subject_motion','camera_and_subject_motion'].includes(v.role) && v.guidance?.enabled) && v.file_exists && v.confirmed && v.linked_to_h3) ? [candidate] : [];
    const picture = draft.pictures.find(p => p.id === candidate.id && candidate.token === `<Picture ${p.slot}>`);
    if (!picture || picture.excluded) return [];
    const users = draft.active_units.filter(u => unitPictureIds(u).includes(picture.id));
    if (users.length && users.every(u=>u.excluded) && !imageGuideRoles.has(picture.role)) return [];
    const bound = users.some(u=>!u.excluded);
    const ready = picture.confirmed && picture.linked_to_h3 && Boolean(picture.description_en?.trim());
    if (picture.role === 'scale_reference') return bound ? [{...candidate,requiresAssociation:false,label:tr`${picture.name||t('Scala')} · Picture ${picture.slot} · riferimento dimensionale`}] : [];
    if (imageGuideRoles.has(picture.role)) return ready && picture.guidance?.enabled ? [{...candidate,requiresAssociation:false,label:tr`${picture.name||t('Guida')} · Picture ${picture.slot} · guida`}] : [];
    if (!bound && !ready) return [];
    return [{ ...candidate, requiresAssociation: !bound,
      label: `${picture.name || t("Immagine")} · Picture ${picture.slot}${bound ? "" : t(" · da associare")}` }];
  });
}

export function associatePicture(draft, pictureId, subject, attribute, replaceIndex = null) {
  const picture = draft.pictures.find(p => p.id === pictureId);
  const unit = draft.active_units.find(u => u.subject === subject);
  const allowed = { character: ["identity", "appearance", "outfit", "shoes"], environment: ["environment", "appearance"], object: ["object", "appearance"] };
  if (picture?.excluded || unit?.excluded || !picture?.confirmed || imageGuideRoles.has(picture.role) || picture.role === 'scale_reference' || !picture.linked_to_h3 || !picture.description_en?.trim() || !allowed[unit?.role]?.includes(attribute)) {
    throw new Error(t("Scegli una Picture pronta e un Subject compatibile con l’attributo."));
  }
  const sources = unit.sources || [];
  if (sources.some(s => s.picture_id === pictureId && s.attribute === attribute)) {
    throw new Error(t("Questa associazione è già presente nel Subject."));
  }
  const source = { picture_id: pictureId, attribute };
  if (replaceIndex === null) unit.sources = [...sources, source];
  else {
    if (!Number.isInteger(replaceIndex) || sources[replaceIndex]?.attribute !== attribute) {
      throw new Error(t("L’associazione da sostituire è cambiata: selezionala di nuovo."));
    }
    unit.sources = sources.map((existing, index) => index === replaceIndex ? source : existing);
  }
  unit.confirmed = false;
}
