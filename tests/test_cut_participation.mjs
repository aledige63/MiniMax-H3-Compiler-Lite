import assert from 'node:assert/strict';
import test from 'node:test';
import {setExcluded,renderParticipation,includedSubjectChoices} from '../app/static/cut-participation.js';
import {visibleReferenceTokens,associatePicture} from '../app/static/reference-menu.js';

test('la spunta preserva dati, conferme e numeri; disattivarla rimuove il campo additivo',()=>{
  const item={subject:3,name:'Vaso',confirmed:true,sources:[{picture_id:'p'}]};
  const before=structuredClone(item);setExcluded(item,true);assert.equal(item.excluded,true);
  setExcluded(item,false);assert.deepEqual(item,before);
});

test('il controllo descrive esplicitamente che la spunta attiva esclude dal cut',()=>{
  const item={id:'p'};let callback,changes=0;
  const node=(tag,className,text)=>({tag,className,text,children:[],append(...items){this.children.push(...items);}});
  const box=renderParticipation(item,'picture',{el:node,checkbox(label,checked,change){callback=change;return {label,checked};},changed(){changes++;}});
  assert.equal(box.children[0].label,'Escludi da questo cut');callback(true);
  assert.equal(item.excluded,true);assert.equal(changes,1);assert.match(box.children[1].text,/Escludi anche i Subject/);
});

test('i richiami omettono Subject esclusi e immagini usate solo da loro, conservando quelle condivise',()=>{
  const picture={id:'p',slot:1,description_en:'a vase',confirmed:true,linked_to_h3:true};
  const unit={subject:1,excluded:true,sources:[{picture_id:'p'}]};
  const tokens=[{kind:'unit',id:'1',token:'<Subject 1>'},{kind:'picture',id:'p',token:'<Picture 1>'}];
  const draft={active_units:[unit],pictures:[picture],dialogues:[]};
  assert.deepEqual(visibleReferenceTokens(tokens,draft),[]);
  draft.active_units.push({subject:2,sources:[{picture_id:'p'}]});
  assert.equal(visibleReferenceTokens(tokens,draft)[0].token,'<Picture 1>');
  setExcluded(picture,true);assert.deepEqual(visibleReferenceTokens(tokens,draft),[]);
});

test('una nuova associazione non riattiva implicitamente riferimenti esclusi',()=>{
  const draft={pictures:[{id:'p',confirmed:true,linked_to_h3:true,description_en:'a vase',excluded:true}],active_units:[{subject:1,role:'object',sources:[]}]};
  assert.throws(()=>associatePicture(draft,'p',1,'object'));
  assert.deepEqual(draft.active_units[0].sources,[]);
});

test('destinatari esclusi già scelti restano visibili e correggibili nei selettori',()=>{
  const choices=includedSubjectChoices([{subject:1,name:'Persona',role:'character'},{subject:3,name:'Vaso',excluded:true}],3,'Scegli');
  assert.deepEqual(choices.map(([id])=>id),['',1,3]);
  assert.match(choices.at(-1)[1],/escluso/);
  assert.deepEqual(includedSubjectChoices([{subject:3,excluded:true}],null,'Scegli'),[['','Scegli']]);
});
