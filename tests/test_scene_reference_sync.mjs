import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
import {mergeSceneReferences, applyLibraryReference, sameReferenceValue} from '../app/static/scene-reference-sync.js';

const base=()=>({request:'Original request',pictures:[{id:'p',slot:1,role:'identity',description_en:'Old image',confirmed:true,linked_to_h3:true}],
  active_units:[{subject:4,name:'Test',description_en:'Old definition',definition_mode:'manual',confirmed:true,sources:[{picture_id:'p',attribute:'identity'}]}]});

test('a shared definition update preserves a locally edited request, slot, mapping and exclusion',()=>{
  const before=base(),local=structuredClone(before),remote=structuredClone(before);
  local.request='Unsaved request';local.pictures[0].slot=7;local.pictures[0].guidance={enabled:false,prompt_en:'Keep this local guide.'};
  local.active_units[0].excluded=true;remote.active_units[0].description_en='Corrected definition';
  const merged=mergeSceneReferences(before,local,remote);
  assert.equal(merged.request,local.request);assert.equal(merged.pictures[0].slot,7);
  assert.deepEqual(merged.pictures[0].guidance,local.pictures[0].guidance);
  assert.equal(merged.active_units[0].description_en,'Corrected definition');assert.equal(merged.active_units[0].excluded,true);
  assert.equal(before.active_units[0].description_en,'Old definition');
});

test('overlapping edits to a shared definition remain a recoverable conflict',()=>{
  const before=base(),local=structuredClone(before),remote=structuredClone(before);
  local.active_units[0].description_en='Local alternative';remote.active_units[0].description_en='Remote alternative';
  assert.equal(mergeSceneReferences(before,local,remote),null);
  local.active_units[0].description_en='Remote alternative';assert.ok(mergeSceneReferences(before,local,remote));
  remote.request='Another browser request';assert.equal(mergeSceneReferences(before,local,remote),null);
});

test('membership, association and slot changes are not mistaken for description synchronization',()=>{
  const before=base();
  for(const modify of [v=>v.pictures[0].slot=2,v=>v.active_units[0].sources=[],v=>v.pictures=[]]){
    const remote=structuredClone(before);modify(remote);assert.equal(mergeSceneReferences(before,before,remote),null);
  }
});

test('an explicit library reload replaces only the selected Subject and keeps other local edits',()=>{
  const local=base(),server=base();local.request='Unsaved local request';local.active_units[0].excluded=true;
  local.active_units.push({subject:5,description_en:'Another locally edited unit'});
  server.active_units[0].description_en='Current library definition';
  const merged=applyLibraryReference(local,server,'unit','stable-unit',{'4':'stable-unit'});
  assert.equal(merged.active_units[0].description_en,'Current library definition');
  assert.equal(merged.request,local.request);assert.equal(merged.active_units[0].excluded,true);
  assert.deepEqual(merged.active_units[1],local.active_units[1]);assert.equal(sameReferenceValue(merged,server),false);
});

const source=await readFile(new URL('../app/static/app.js',import.meta.url),'utf8');
const library=source.slice(source.indexOf('async function openLibrary()'),source.indexOf('function updateConfirmationButtons()'));
function libraryFixture(accepted=false){
  const nodes=new Map(),node=()=>({children:[],append(...values){this.children.push(...values);},replaceChildren(...values){this.children=values;},setAttribute(){}});
  const before=base(),local=structuredClone(before);local.request='Keep this unsaved request';
  const context={workspace:{id:'cut',project_id:'project',scene_id:'scene',revision:1,draft_input:before,unit_ids:{'4':'unit'}},draft:local,
    draftDirty:true,draftTick:2,manualDirty:true,structuredClone,clone:structuredClone,t:v=>v,tr:(p,...v)=>String.raw({raw:p},...v),
    saveDraft:async()=>{throw Error('Library must open without saving');},newCommandId:()=> 'command',
    request:async path=>path.includes('/library')?{units:[{id:'unit',subject:4,name:'Test',sources:[]}],pictures:[],revision:1}:context.workspace,
    el:node,button:node,$:id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);},roles:[],
    currentContext:()=>({scene:{finalized:false}}),unitPictureIds:()=>[],
    renderLibraryRows:(data,state,ui)=>{if(accepted)ui.choose('unit',data.units[0]);return [];},
    dialog:async()=>{context.opened=true;return accepted;},normalizeDraft:structuredClone,
    applyLibraryReference,sameReferenceValue,renderDraft(){},renderResults(){},feedback(){},
    mutation:async(method,url,command,apply)=>{const view=structuredClone(context.workspace);view.revision=2;view.draft_input.active_units[0].description_en='Updated definition';apply(view);}
  };
  vm.createContext(context);vm.runInContext(library,context);return context;
}
test('the real library handler opens with dirty fields even when saving would fail',async()=>{
  const c=libraryFixture();await c.openLibrary();assert.equal(c.opened,true);assert.equal(c.draft.request,'Keep this unsaved request');
});
test('the real library handler reloads Subject 4 while preserving unsaved request and manual editor state',async()=>{
  const c=libraryFixture(true);await c.openLibrary();assert.equal(c.draft.request,'Keep this unsaved request');
  assert.equal(c.draft.active_units[0].description_en,'Updated definition');assert.equal(c.draftDirty,true);assert.equal(c.manualDirty,true);
});

test('the real save handler rebases synchronized descriptions before saving unsaved local request',async()=>{
  const before=base(),remote=structuredClone(before),local=structuredClone(before);
  remote.active_units[0].description_en='Shared corrected definition';local.request='Unsaved local request';
  const workspace={id:'cut',revision:1,draft_input:before,unit_revisions:{4:1},reference_revisions:{p:1}};
  const fresh={...structuredClone(workspace),revision:2,draft_input:remote,unit_revisions:{4:2}};
  let sent;
  const c={workspace,draft:local,draftTick:3,draftDirty:true,structuredClone,clone:structuredClone,
    mergeSceneReferences,sameReferenceValue,normalizeDraft:structuredClone,t:v=>v,
    request:async()=>fresh,shotPresetSnapshots:()=>[],newCommandId:()=> 'save',compileFailure:null,
    renderDraft(){},renderTokens(){},renderContinuity(){},renderContinuityPreview(){},$:()=>({}),
    mutation:async(method,url,command,apply)=>{sent=command;apply({...fresh,revision:3,draft_input:command.input});}};
  vm.createContext(c);vm.runInContext(source.slice(source.indexOf('async function saveDraft()'),source.indexOf('async function addItem(')),c);
  assert.equal(await c.saveDraft(),true);assert.equal(sent.expected_revision,2);
  assert.equal(sent.input.request,'Unsaved local request');
  assert.equal(sent.input.active_units[0].description_en,'Shared corrected definition');assert.equal(c.draftDirty,false);
});

test('saving manual text refreshes reference revisions even when the draft fields are clean',async()=>{
  let refreshed=false,saved;
  const c={workspace:{id:'cut',revision:1},draftDirty:false,manualDirty:true,manualBaseId:'base',
    refreshReferencesBeforeSave:async()=>{refreshed=true;c.workspace.revision=2;return true;},
    $:()=>({value:'Exact unsaved manual text.\n'}),newCommandId:()=> 'manual',t:v=>v,
    mutation:async(method,url,command,apply)=>{saved=command;apply({id:'cut',revision:3,manual_version_id:'manual'});},
    refreshProjects:async()=>{},renderNavigation(){},renderConfirmedCuts(){},feedback(){}};
  vm.createContext(c);vm.runInContext(source.slice(source.indexOf('async function saveManual()'),source.indexOf('async function copyText(')),c);
  await c.saveManual();assert.equal(refreshed,true);assert.equal(saved.expected_revision,2);
  assert.equal(saved.text,'Exact unsaved manual text.\n');assert.equal(c.manualDirty,false);
});
