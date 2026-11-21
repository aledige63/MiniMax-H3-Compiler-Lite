import { t, tr } from "./i18n.js";

import { imageGuideRoles } from './reference-menu.js';

export const physicalOperations = [['add', t('Aggiunta')], ['replace', t('Sostituzione')], ['modify', t('Modifica')]];

export function addPhysicalDetail(unit) {
  const details = unit.physical_details ||= [];
  if (details.length >= 20) return;
  let number = 1;
  while (details.some(detail => detail.id === `p${number}`)) number++;
  details.push({id:`p${number}`, description:'', body_location:'', operation:'add', picture_id:null});
  unit.confirmed = false;
}

export function renderPhysicalDetails(unit, pictures, continuityMode, ui) {
  const {el, field, selectField, button, changed, redraw} = ui;
  const section = el('details', 'physical-details');
  const details = unit.physical_details || [];
  section.open = Boolean(details.length);
  section.append(el('summary', '', tr`Dettagli fisici e modifiche${details.length ? ` · ${details.length}` : ''}`));
  section.append(el('p', 'field-help', t('Descrivi il dettaglio e la sua posizione anche in italiano. Destra e sinistra sono quelle del personaggio. La compilazione traduce questi campi e li applica a definizione, retention e azioni.')));
  if (unit.role !== 'character') section.append(el('p', 'issues', t('Questi dettagli richiedono il ruolo Personaggio. Rimuovili oppure ripristina il ruolo.')));
  for (const [index, detail] of details.entries()) {
    const row = el('div', 'source-row');
    row.append(el('strong', '', tr`Dettaglio ${index + 1}`));
    const change = (key, value) => { detail[key] = value; changed(); };
    const fields = el('div', 'two-fields');
    fields.append(selectField(t('Operazione'), detail.operation, physicalOperations, value => change('operation', value)),
      field(t('Posizione sul corpo'), detail.body_location, value => change('body_location', value), {placeholder:t('Es. mano destra del personaggio')}));
    const choices = [['', t('Nessuna Picture · solo descrizione')], ...pictures.filter(p => !imageGuideRoles.has(p.role) && p.role !== 'scale_reference').map(p => [p.id, `${p.name || t('Immagine')} · Picture ${p.slot}`])];
    if (detail.picture_id && !choices.some(([id]) => id === detail.picture_id)) choices.push([detail.picture_id, t('Picture rimossa o con ruolo guida/dimensionale · scegli di nuovo')]);
    if (detail.origin === 'context' || continuityMode !== 'none') choices.push(['__context__', t('Dal contesto di continuità dichiarato')]);
    const source = selectField(t('Picture del dettaglio · facoltativa'), detail.origin === 'context' ? '__context__' : detail.picture_id || '', choices, value => {
      detail.origin = value === '__context__' ? 'context' : 'picture';
      detail.picture_id = value && value !== '__context__' ? value : null;
      changed(); redraw();
    });
    row.append(fields, field(t('Descrizione del dettaglio'), detail.description, value => change('description', value), {placeholder:t('Es. uncino di ferro con attacco in cuoio al polso')}), source);
    if (detail.picture_id && !pictures.some(p => p.id === detail.picture_id && !imageGuideRoles.has(p.role) && p.role !== 'scale_reference')) row.append(el('p', 'issues', t('La Picture non è disponibile per questo dettaglio. Scegli un’immagine oppure nessuna Picture; il collegamento non viene sostituito automaticamente.')));
    if (detail.origin === 'context' && continuityMode === 'none') row.append(el('p', 'issues', t('Dichiara la continuità oppure scegli una Picture o solo descrizione.')));
    row.append(button(t('Rimuovi dettaglio'), 'button subtle danger', () => {
      unit.physical_details.splice(index, 1); changed(); redraw();
    }));
    section.append(row);
  }
  const add = button(t('+ Dettaglio fisico'), 'button subtle', () => { addPhysicalDetail(unit); changed(); redraw(); });
  add.disabled = details.length >= 20 || unit.role !== 'character';
  section.append(add);
  return section;
}
