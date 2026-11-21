import assert from 'node:assert/strict';
import test from 'node:test';
import {createStudioLayout, issueSections, sectionCounts} from '../app/static/studio-layout.js';

class Element {
  constructor(dataset = {}) {this.dataset = dataset; this.events = {}; this.attributes = {}; this.style = {setProperty:(key,value)=>{this.attributes[key] = value;}};this.scrollTop = 0;this.tagName = 'SECTION';}
  setAttribute(key, value) {this.attributes[key] = value;}
  addEventListener(type, handler) {this.events[type] = handler;}
  removeEventListener(type) {delete this.events[type];}
  fire(type, extra = {}) {let prevented = false;this.events[type]?.({target:this,preventDefault(){prevented = true;},...extra});return prevented;}
  querySelector(selector) {this.children ||= {}; return this.children[selector] ||= new Element();}
  focus() {this.focused = true;}
  getBoundingClientRect() {return {width:1000, right:1000, height:800, top:0};}
}

function fixture(preferences = null, unavailableStorage = false) {
  const keys = ['images','subjects','direction','dialogues','audio','video','continuity','versions','settings'];
  const buttons = keys.map(key => new Element({studioSection:key}));
  const panels = keys.map(key => new Element({studioPanel:key}));
  panels[2].tagName = 'DETAILS';
  const nodes = Object.fromEntries(['element-panels','studio-section','application','results-resize','prompt-resize','studio-workspace','results-column'].map(id=>[id,new Element()]));
  nodes['studio-section'].options = keys.map(value => ({value}));
  const doc = new Element();
  doc.getElementById = id => nodes[id];
  doc.querySelectorAll = selector => selector === '[data-studio-section]' ? buttons : panels;
  const classes = new Set();doc.body = {classList:{add:key=>classes.add(key),remove:(...keys)=>keys.forEach(key=>classes.delete(key))}};
  const win = new Element();let stored = preferences;
  win.localStorage = {getItem(){if(unavailableStorage)throw new Error('storage blocked');return stored;},setItem(key,value){if(unavailableStorage)throw new Error('storage blocked');stored = value;}};
  const layout = createStudioLayout(doc,win);
  return {layout, nodes, doc, win, buttons, panels, stored:()=>JSON.parse(stored)};
}

test('cambiare sezione conserva richiesta e risultati e non modifica la bozza', () => {
  const {layout, nodes, panels, buttons} = fixture();
  const draft = {request:'Azione locale', pictures:[{id:'picture'}],active_units:[{subject:1}],dialogues:[]};
  const original = structuredClone(draft);
  layout.update(draft,{id:'cut-1',versions:[],catalogue_issues:[]});
  nodes['element-panels'].scrollTop = 150;nodes['element-panels'].fire('scroll');
  buttons[2].fire('click');
  assert.equal(panels[2].hidden,false);assert.equal(panels[2].open,true);
  assert.equal(panels[1].hidden,true);assert.equal(nodes['studio-section'].value,'direction');
  nodes['element-panels'].scrollTop = 45;nodes['element-panels'].fire('scroll');
  layout.selectSection('subjects');assert.equal(nodes['element-panels'].scrollTop,150);
  layout.selectSection('direction');assert.equal(nodes['element-panels'].scrollTop,45);
  assert.deepEqual(draft,original);
});

test('il selettore compatto e il menu laterale mostrano la stessa sezione', () => {
  const {nodes, panels, buttons, stored} = fixture();
  nodes['studio-section'].value = 'audio';nodes['studio-section'].fire('change');
  assert.equal(panels[4].hidden,false);assert.equal(buttons[4].attributes['aria-pressed'],'true');
  assert.equal(stored().section,'audio');
});

test('un nuovo cut azzera lo scroll senza cambiare la sezione o conservare dati del cut', () => {
  const {layout,nodes,stored} = fixture();
  layout.update({}, {id:'first'});layout.selectSection('images');
  nodes['element-panels'].scrollTop = 200;nodes['element-panels'].fire('scroll');
  layout.update({request:'Riservata'}, {id:'second'});
  assert.equal(nodes['element-panels'].scrollTop,0);
  assert.equal(stored().section,'images');assert.equal(stored().request,undefined);
});

test('contatori e avvisi delle sezioni nascoste derivano dai dati reali', () => {
  const {layout,buttons,nodes} = fixture();
  const draft = {pictures:[{},{}],active_units:[{}],dialogues:[{}],audio_references:[],videos:[],camera:{placement:'as_requested'},continuity:{mode:'none'}};
  assert.equal(sectionCounts(draft,{}).direction,0);
  layout.update(draft,{id:'cut',versions:[{},{},{}],catalogue_issues:['Subject 1 — spunta la conferma.','Picture 2 — collega a H3.']});
  assert.equal(buttons[0].querySelector('[data-studio-count]').textContent,'2');
  assert.equal(buttons[1].querySelector('.studio-warning').hidden,false);
  assert.match(buttons[1].attributes['aria-label'], /controlli da completare/);
  assert.equal(nodes['studio-section'].options[1].textContent,'Subject · 1 · da completare');
  assert.equal(buttons[7].querySelector('[data-studio-count]').textContent,'3');
  layout.update(draft,{id:'cut',catalogue_issues:[]});
  assert.equal(buttons[1].querySelector('.studio-warning').hidden,true);
  assert.equal(issueSections(['Battuta d1 — conferma.']).dialogues.length,1);
});

test('i divisori si regolano da tastiera entro limiti persistenti', () => {
  const {nodes,stored} = fixture();
  assert.equal(nodes['results-resize'].fire('keydown',{key:'ArrowLeft'}),true);
  assert.equal(nodes.application.attributes['--results-share'],'44%');
  nodes['results-resize'].fire('keydown',{key:'End'});assert.equal(stored().results,52);
  nodes['results-resize'].fire('keydown',{key:'ArrowLeft'});assert.equal(stored().results,52);
  nodes['prompt-resize'].fire('keydown',{key:'Home'});assert.equal(stored().proposal,35);
  nodes['prompt-resize'].fire('keydown',{key:'ArrowDown'});assert.equal(stored().proposal,37);
  assert.equal(nodes['prompt-resize'].fire('keydown',{key:'Tab'}),false);
});

test('trascinamento e annullamento rilasciano i gestori e mantengono la dimensione scelta', () => {
  const {nodes,doc,win,stored} = fixture();
  nodes['results-resize'].fire('pointerdown',{button:0});
  doc.fire('pointermove',{clientX:600});
  assert.equal(nodes.application.attributes['--results-share'],'40%');
  doc.fire('pointercancel');assert.equal(stored().results,40);assert.equal(doc.events.pointermove,undefined);
  nodes['prompt-resize'].fire('pointerdown',{button:0});
  doc.fire('pointermove',{clientY:400});win.fire('blur');
  assert.equal(stored().proposal,50);assert.equal(doc.events.pointermove,undefined);
});

test('preferenze errate o memoria locale non disponibile non bloccano l’app', () => {
  for (const saved of ['invalid json', JSON.stringify({section:'__proto__',results:1000,proposal:-10})]) {
    const {nodes} = fixture(saved);
    assert.equal(nodes['studio-section'].value,'subjects');
    if (saved !== 'invalid json') {
      assert.equal(nodes.application.attributes['--results-share'],'52%');
      assert.equal(nodes.application.attributes['--proposal-share'],'35%');
    }
  }
  const {layout,nodes} = fixture(null,true);layout.selectSection('video');
  assert.equal(nodes['studio-section'].value,'video');
});
