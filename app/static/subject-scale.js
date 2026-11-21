import { t } from "./i18n.js";

import {imageGuideRoles} from './reference-menu.js?v=subject-scale';

export function updateScale(unit, patch) {
  const scale = {...(unit.scale || {}), ...patch};
  if (!Object.values(scale).some(value => value !== null && value !== undefined && value !== '')) delete unit.scale;
  else unit.scale = scale;
  unit.confirmed = false;
}

export function renderSubjectScale(unit, units, pictures, unitIds, ui) {
  const {el, field, selectField, button, changed, redraw} = ui;
  const section = el('details', 'physical-details subject-scale');
  section.open = Boolean(unit.scale);
  section.append(el('summary', '', t('Dimensioni e scala')));
  section.append(el('p', 'field-help', t('Indica misure e/o un confronto, anche in italiano. Il prompt richiederà di mantenere le proporzioni fisiche durante il cut, lasciando variare la grandezza apparente con distanza e prospettiva.')));
  const change = (patch, refresh = false) => { updateScale(unit, patch); changed(); if (refresh) redraw(); };
  const measurements = field(t('Misure · facoltative'), unit.scale?.measurements || '', value => change({measurements:value}),
    {placeholder:t('Es. altezza 20 cm, diametro 6 cm')});
  const comparison = field(t('Confronto dimensionale'), unit.scale?.comparison || '', value => change({comparison:value}),
    {placeholder:t('Es. la bottiglietta si impugna comodamente con una mano, come nella foto')});
  measurements.querySelector?.('input')?.setAttribute('maxlength', '500');
  comparison.querySelector?.('input')?.setAttribute('maxlength', '700');
  const choices = [['', t('Nessun Subject · confronto descritto nel testo o nella foto')],
    ...units.filter(other => other.subject !== unit.subject && !other.excluded && unitIds[String(other.subject)])
      .map(other => [unitIds[String(other.subject)], `${other.name || t('Unità')} · Subject ${other.subject}`])];
  const selected = unit.scale?.reference_subject_id || '';
  if (selected && !choices.some(([id]) => id === selected)) choices.push([selected, t('Subject di confronto assente o escluso · scegli di nuovo')]);
  const targets = selectField(t('Subject di confronto · facoltativo'), selected, choices, value => {
    const number = Object.keys(unitIds).find(key => unitIds[key] === value);
    change({reference_subject_id:value || null, reference_subject:number ? Number(number) : null}, true);
  });
  const images = [['', t('Nessuna Picture · solo indicazioni scritte')], ...pictures.filter(p => !p.excluded && !imageGuideRoles.has(p.role))
    .map(p => [p.id, `${p.name || t('Immagine')} · Picture ${p.slot}${p.role === 'scale_reference' ? t(' · riferimento dimensionale') : ''}`])];
  const pictureId = unit.scale?.picture_id || '';
  if (pictureId && !images.some(([id]) => id === pictureId)) images.push([pictureId, t('Picture rimossa, esclusa o guida · scegli di nuovo')]);
  const picture = selectField(t('Picture di riferimento dimensionale · facoltativa'), pictureId, images,
    value => change({picture_id:value || null}, true));
  section.append(measurements, comparison, targets, picture,
    el('p', 'field-help', t('Puoi scegliere la stessa Picture che definisce l’oggetto: occupa un solo slot. Descrivi il rapporto visibile, per esempio bottiglietta/mano. La persona nella foto non diventa un Subject; le misure non vengono stimate automaticamente.')));
  if (selected && !units.some(other => other.subject !== unit.subject && !other.excluded && unitIds[String(other.subject)] === selected)) {
    section.append(el('p', 'issues', t('Il Subject di confronto non partecipa al cut. Riattivalo, aggiungilo dalla libreria oppure scegli un altro riferimento.')));
  }
  if (unit.scale) section.append(button(t('Rimuovi dimensioni e scala'), 'button subtle danger', () => {
    delete unit.scale; unit.confirmed = false; changed(); redraw();
  }));
  return section;
}
