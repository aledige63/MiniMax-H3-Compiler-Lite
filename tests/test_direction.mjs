import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import {cameraPreview,hasCameraSelection,cameraTag,shotPresetSnapshots} from '../app/static/direction.js';
import {visibleReferenceTokens,associatePicture} from '../app/static/reference-menu.js';
const options=JSON.parse(await readFile(new URL('../app/static/direction-options.json',import.meta.url),'utf8'));
test('tag riutilizzabili e snapshot soltanto delle inquadrature richiamate',()=>{
  assert.equal(cameraTag('Primo piano · lento'),'primo_piano_lento');
  const library=[{id:'a',tag:'primo_piano'},{id:'b',tag:'figura_intera'}];
  assert.deepEqual(shotPresetSnapshots('#primo_piano. A 3 secondi #primo_piano',library),[library[0]]);
  assert.throws(()=>shotPresetSnapshots('#sconosciuta',library),/non disponibili/);
});

test('camera assente non aggiunge una regia predefinita',()=>{
  assert.equal(cameraPreview(null,options),'');assert.equal(hasCameraSelection({subject:1,placement:'opening'}),false);
});
test('inquadratura, Dutch angle, movimento e velocità si compongono senza confondere zoom e dolly',()=>{
  const preview=cameraPreview({framing:'american',angle:'dutch',movement:'push_in',speed:'slow',amplitude:'small',subject:1},options);
  assert.match(preview,/knees/);assert.match(preview,/Dutch angle/);assert.match(preview,/pushes in with small amplitude at slow speed/);assert.match(preview,/<Subject 1>/);
  assert.match(cameraPreview({movement:'zoom_in'},options),/zooms in/);assert.doesNotMatch(cameraPreview({movement:'zoom_in'},options),/pushes/);
});
test('una Picture guida attiva si inserisce senza creare o associare Subject',()=>{
  const draft={active_units:[],dialogues:[],pictures:[{id:'g',slot:2,role:'style',name:'Style',description_en:'ink',confirmed:true,linked_to_h3:true,guidance:{enabled:true}}]};
  const tokens=[{kind:'picture',id:'g',token:'<Picture 2>'}];
  assert.equal(visibleReferenceTokens(tokens,draft)[0].requiresAssociation,false);
  assert.throws(()=>associatePicture(draft,'g',1,'identity'));
  draft.pictures[0].guidance.enabled=false;assert.equal(visibleReferenceTokens(tokens,draft).length,0);
});
test('i Video guida non sono continuazione implicita e richiedono conferma',()=>{
  const draft={active_units:[],dialogues:[],pictures:[],continuity:{mode:'none'},videos:[{id:'v1',slot:1,role:'camera',confirmed:true,linked_to_h3:true,file_exists:true,guidance:{enabled:true}}]};
  const tokens=[{kind:'video',id:'v1',token:'<Video 1>'}];assert.equal(visibleReferenceTokens(tokens,draft).length,1);
  draft.videos[0].confirmed=false;assert.equal(visibleReferenceTokens(tokens,draft).length,0);
});
