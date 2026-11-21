import assert from 'node:assert/strict';
import test from 'node:test';
import {addPhysicalDetail, renderPhysicalDetails} from '../app/static/physical-details.js';
import {unitPictureIds, visibleReferenceTokens} from '../app/static/reference-menu.js';

function fixture(unit, pictures = [], continuity = 'none') {
  const controls = [];
  const ui = {
    changes:0, redraws:0,
    el(tag, className, text) { return {tag, className, text, children:[], append(...items) {this.children.push(...items);}}; },
    field(label, value, change) { const node = {label, value, change}; controls.push(node); return node; },
    selectField(label, value, choices, change) { const node = {label, value, choices, change}; controls.push(node); return node; },
    button(text, className, click) { const node = {text, click}; controls.push(node); return node; },
    changed() {unit.confirmed = false; ui.changes++;},
    redraw() {ui.redraws++;},
  };
  const section = renderPhysicalDetails(unit, pictures, continuity, ui);
  return {section, controls, ui};
}

test('i dettagli sono locali al Subject, riusano il primo ID libero e richiedono conferma', () => {
  const unit = {role:'character', confirmed:true, physical_details:[{id:'p2'}]};
  addPhysicalDetail(unit);
  assert.equal(unit.physical_details[1].id, 'p1');
  assert.equal(unit.confirmed, false);
  assert.equal(unit.physical_details[1].picture_id, null);
  const other = {role:'character'}; addPhysicalDetail(other);
  assert.equal(other.physical_details[0].id, 'p1');
});

test('la sezione modifica posizione, operazione e descrizione senza cambiare le altre sorgenti', () => {
  const unit = {role:'character', confirmed:true, sources:[{attribute:'identity', picture_id:'face'}]};
  let view = fixture(unit);
  assert.match(view.section.children[0].text, /Dettagli fisici e modifiche/);
  view.controls.find(c => c.text === '+ Dettaglio fisico').click();
  assert.equal(view.ui.changes, 1); assert.equal(view.ui.redraws, 1);
  view = fixture(unit);
  view.controls.find(c => c.label === 'Operazione').change('replace');
  view.controls.find(c => c.label === 'Posizione sul corpo').change('mano destra');
  view.controls.find(c => c.label === 'Descrizione del dettaglio').change('un uncino');
  assert.equal(unit.physical_details[0].operation, 'replace');
  assert.equal(unit.physical_details[0].body_location, 'mano destra');
  assert.equal(unit.physical_details[0].description, 'un uncino');
  assert.deepEqual(unit.sources, [{attribute:'identity', picture_id:'face'}]);
  view.controls.find(c => c.text === 'Rimuovi dettaglio').click();
  assert.deepEqual(unit.physical_details, []);
});

test('la Picture del dettaglio è una dipendenza e un riferimento già associato allo stesso Subject', () => {
  const unit = {subject:1, role:'character', sources:[{picture_id:'face'}], physical_details:[{id:'p1', picture_id:'hook'}]};
  assert.deepEqual(unitPictureIds(unit), ['face', 'hook']);
  const picture = {id:'hook', slot:3, role:'object', name:'Uncino', description_en:'an iron hook', confirmed:true, linked_to_h3:true};
  const tokens = visibleReferenceTokens([{kind:'picture', id:'hook', token:'<Picture 3>'}], {active_units:[unit], pictures:[picture]});
  assert.equal(tokens[0].requiresAssociation, false);
  assert.doesNotMatch(tokens[0].label, /da associare/);
});

test('la selezione conserva riferimenti rimossi, esclude guide e cambia origine solo su scelta esplicita', () => {
  const unit = {role:'character', confirmed:true, physical_details:[{id:'p1', picture_id:'removed', operation:'replace'}]};
  const {controls, section, ui} = fixture(unit, [{id:'guide', role:'style'}, {id:'hook', slot:4, role:'object'}], 'latent');
  const menu = controls.find(c => c.label === 'Picture del dettaglio · facoltativa');
  assert.equal(menu.value, 'removed');
  assert.equal(menu.choices.some(([key]) => key === 'guide'), false);
  assert.ok(section.children.some(child => child.children?.some(node => /Picture non è disponibile/.test(node.text))));
  menu.change('hook');
  assert.equal(unit.physical_details[0].picture_id, 'hook'); assert.equal(unit.confirmed, false);
  menu.change('__context__');
  assert.equal(unit.physical_details[0].origin, 'context'); assert.equal(unit.physical_details[0].picture_id, null);
  menu.change('');
  assert.equal(unit.physical_details[0].origin, 'picture'); assert.equal(unit.physical_details[0].picture_id, null);
  assert.equal(ui.redraws, 3);
});

test('un dettaglio dal contesto rimane visibile quando manca il raccordo e non viene convertito in Picture', () => {
  const unit = {role:'character', physical_details:[{id:'p1', origin:'context', picture_id:null}]};
  const {controls, section} = fixture(unit);
  assert.equal(controls.find(c => c.label === 'Picture del dettaglio · facoltativa').value, '__context__');
  assert.ok(section.children.some(child => child.children?.some(node => /Dichiara la continuità/.test(node.text))));
  assert.equal(unit.physical_details[0].origin, 'context');
});

test('i dettagli restano correggibili dopo un cambio di ruolo e il limite non aggiunge righe', () => {
  const unit = {role:'object', physical_details:[{id:'p1'}]};
  const {controls} = fixture(unit);
  assert.equal(controls.find(c => c.text === '+ Dettaglio fisico').disabled, true);
  controls.find(c => c.text === 'Rimuovi dettaglio').click();
  assert.equal(unit.physical_details.length, 0);
  const full = {physical_details:Array.from({length:20}, (_, i) => ({id:`p${i + 1}`}))};
  addPhysicalDetail(full); assert.equal(full.physical_details.length, 20);
});
