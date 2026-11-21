import assert from 'node:assert/strict';
import test from 'node:test';
import {renderLibraryRows} from '../app/static/project-library.js';

const item={id:'picture',name:'Giacca',description_en:'A green jacket',revision:3};
const unit={id:'unit',name:'Persona',subject:1,role:'character',sources:[{picture_id:'picture'}]};
function fixture(library,overrides={}) {
  const controls=[],actions=[];
  const state={trashed:false,busy:false,canReuse:true,pictureIds:new Set(),unitIds:new Set(),...overrides};
  const ui={
    el(tag,className,text){return {tag,className,text,children:[],append(...nodes){this.children.push(...nodes);}};},
    button(text,className,click){const node={text,click,setAttribute(key,value){this[key]=value;}};controls.push(node);return node;},
    roleLabel:role=>role, choose:(...args)=>actions.push(['choose',...args]),setTrash:(...args)=>actions.push(['trash',...args])
  };
  return {rows:renderLibraryRows(library,state,ui),controls,actions};
}

test('il cestino agisce su ID di libreria e offre ripristino per immagini e Subject',()=>{
  const first=fixture({pictures:[item],units:[unit]});
  first.controls.find(c=>c['aria-label']==='Cestina immagine Giacca').click();
  first.controls.find(c=>c['aria-label']==='Cestina Subject Persona').click();
  assert.deepEqual(first.actions,[['trash','picture',item,true],['trash','unit',unit,true]]);
  const trash=fixture({trashed_pictures:[item],trashed_units:[unit]},{trashed:true});
  assert.equal(trash.controls.some(c=>c.text.startsWith('Usa')),false);
  trash.controls.find(c=>c['aria-label']==='Ripristina immagine Giacca').click();
  assert.deepEqual(trash.actions,[['trash','picture',item,false]]);
});

test('un Subject con immagini cestinate non può essere riusato e spiega il ripristino',()=>{
  const {rows,controls}=fixture({pictures:[],units:[unit],trashed_pictures:[item]});
  assert.equal(controls.find(c=>c.text==='Usa Subject').disabled,true);
  assert.match(rows[0].children[0].children.at(-1).text,/Ripristina prima/);
  assert.equal(controls.find(c=>c['aria-label']==='Cestina Subject Persona').disabled,false);
});

test('scene chiuse consentono gestione libreria ma non riuso; le richieste in corso bloccano i pulsanti',()=>{
  const closed=fixture({pictures:[item]},{canReuse:false});
  assert.equal(closed.controls.find(c=>c.text==='Usa immagine').disabled,true);
  assert.equal(closed.controls.find(c=>c.text==='Sposta nel cestino').disabled,false);
  const pending=fixture({pictures:[item],units:[unit]},{busy:true});
  assert.ok(pending.controls.every(c=>c.disabled));
});

test('elementi senza nome restano gestibili e ricaricare usa le identità del cut',()=>{
  const unnamed={...unit,name:''};
  const {controls}=fixture({units:[unnamed],pictures:[item]},{unitIds:new Set(['unit']),pictureIds:new Set(['picture'])});
  assert.ok(controls.find(c=>c.text==='Ricarica Subject'));
  assert.ok(controls.find(c=>c.text==='Ricarica immagine'));
  assert.ok(controls.find(c=>c['aria-label']==='Cestina Subject Subject senza nome'));
});
