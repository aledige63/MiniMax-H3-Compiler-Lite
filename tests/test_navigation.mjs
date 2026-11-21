import {t, tr, diagnostic, uiLanguage} from '../app/static/i18n.js';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import test from 'node:test';

const source=await readFile(new URL('../app/static/app.js',import.meta.url),'utf8');
const between=(start,end)=>source.slice(source.indexOf(start),source.indexOf(end,source.indexOf(start)));

test('il dropdown acquisisce il cut scelto prima che il blocco comandi ridisegni i menu',()=>{
  const menu={value:'cut-2'};let opened;
  const context={$:()=>menu,withCommand:action=>{menu.value='cut-1';action();},switchCut:id=>{opened=id;}};
  Object.assign(context, {t, tr, diagnostic, uiLanguage});
  vm.runInNewContext(between('$("cut-select").onchange =','for (const kind of ["project"'),context);
  menu.onchange({currentTarget:menu});
  assert.equal(opened,'cut-2');
});

function refreshFixture(){
  const nodes={application:{hidden:false},'action-dialog':{open:false},'refresh-cut':{},'manual-text':{value:''},recovery:{hidden:true}};
  const context={refreshBusy:false,commandBusy:false,navigationBusy:false,pending:null,
    workspace:{id:'cut-1',revision:1},draftTick:3,draftDirty:false,manualDirty:false,
    document:{hidden:false},$:id=>nodes[id],projects:[],renderNavigation(){},renderNotice(){},feedback(){},
    applyWorkspace(view){this.unused=view;},request:async path=>path==='/api/projects'?[]:{id:'cut-1',revision:2}};
  context.applyWorkspace=view=>{context.applied=view;context.workspace=view;};
  Object.assign(context, {t, tr, diagnostic, uiLanguage});
  vm.createContext(context);vm.runInContext(between('async function refreshCurrentCut(', '$("refresh-cut").onclick'),context);
  return {context,nodes};
}

test('un altro browser aggiorna immagini e proposta del cut pulito senza salvare o compilare',async()=>{
  const {context}=refreshFixture();const paths=[];
  context.request=async path=>{paths.push(path);return path==='/api/projects'?[]:{id:'cut-1',revision:2,media_by_picture:{p:'new-media'},latest_candidate_id:'new-prompt'};};
  await context.refreshCurrentCut(true);
  assert.equal(context.applied.media_by_picture.p,'new-media');assert.equal(context.applied.latest_candidate_id,'new-prompt');
  assert.deepEqual(paths,['/api/cuts/cut-1','/api/projects']);
});

test('modifiche locali e testo manuale non vengono sovrascritti dalla sincronizzazione',async()=>{
  for(const flag of ['draftDirty','manualDirty']){
    const {context,nodes}=refreshFixture();context[flag]=true;nodes['manual-text'].value='local text';
    await context.refreshCurrentCut(true);
    assert.equal(context.applied,undefined);assert.equal(nodes.recovery.hidden,false);
    assert.equal(nodes['manual-text'].value,'local text');assert.equal(context.workspace.revision,1);
  }
});

test('digitare durante la lettura remota preserva i campi',async()=>{
  const {context,nodes}=refreshFixture();context.request=async path=>{
    if(path==='/api/projects')return [];
    context.draftTick++;nodes['manual-text'].value='typed during load';return {id:'cut-1',revision:2};
  };
  await context.refreshCurrentCut(true);
  assert.equal(context.applied,undefined);assert.equal(nodes['manual-text'].value,'typed during load');
});

test('una risposta tardiva non riapre il cut precedente',async()=>{
  const {context}=refreshFixture();context.request=async path=>{
    if(path==='/api/projects')return [];
    context.workspace={id:'cut-2',revision:1};return {id:'cut-1',revision:2};
  };
  await context.refreshCurrentCut(true);
  assert.equal(context.applied,undefined);assert.equal(context.workspace.id,'cut-2');
  vm.runInContext(between('function mergePolledView(', 'function startAssistancePolling('),context);
  context.mergePolledView({id:'cut-1',revision:99});assert.equal(context.workspace.id,'cut-2');
});

test('una richiesta fallita lascia recuperabile la vista corrente',async()=>{
  const {context,nodes}=refreshFixture();let feedback;
  context.request=async()=>{throw new Error('offline');};context.feedback=message=>{feedback=message;};
  await context.refreshCurrentCut(true);
  assert.equal(context.workspace.id,'cut-1');assert.equal(context.refreshBusy,false);assert.equal(nodes['refresh-cut'].disabled,false);assert.equal(feedback,'offline');
});

test('una lettura iniziata prima di un salvataggio locale non ripristina una revisione precedente',async()=>{
  const {context}=refreshFixture();context.request=async path=>{
    if(path==='/api/projects')return [];
    context.workspace={id:'cut-1',revision:3,latest_candidate_id:'new-local-prompt'};
    return {id:'cut-1',revision:2,latest_candidate_id:'older-remote-prompt'};
  };
  await context.refreshCurrentCut(true);
  assert.equal(context.applied,undefined);assert.equal(context.workspace.latest_candidate_id,'new-local-prompt');
});

function savedItemFixture(editDuringRequest = false) {
  const draft = {request:'Saved request', pictures:[], active_units:[{subject:1, confirmed:true, sources:[]}]};
  const context = {
    draft, draftDirty:false, draftTick:1,
    workspace:{id:'cut-1', revision:1, draft_input:structuredClone(draft)},
    saveDraft:async () => true, newCommandId:() => 'command-1',
    studioLayout:{selectSection(section){context.selectedSection = section;}},
    clone:structuredClone, normalizeDraft:structuredClone, feedback(){}, renderDraft(){}, renderResults(){},
    markDraft(){ context.draftDirty = true; context.draftTick++; },
    async mutation(method, path, body, apply) {
      const view = structuredClone(context.workspace);
      view.revision++;
      if (path.endsWith('/items')) view.draft_input.pictures.push({id:'picture-1'});
      else {
        const unit = view.draft_input.active_units[0];
        unit.confirmed = false;
        unit.sources.push({picture_id:null, attribute:'identity'});
      }
      if (editDuringRequest) {
        context.draft.request = 'New local edit';
        context.markDraft();
      }
      apply(view);
    },
  };
  Object.assign(context, {t, tr, diagnostic, uiLanguage});
  vm.runInNewContext(between('async function addItem(', 'async function compile(') +
    between('function adoptView(', 'async function uploadPicture('), context);
  return context;
}

test('elementi e associazioni già registrati lasciano la bozza disponibile agli aggiornamenti', async () => {
  const context = savedItemFixture();
  await context.addItem('picture');
  assert.equal(context.selectedSection, 'images');
  assert.equal(context.draft.pictures[0].id, 'picture-1');
  assert.equal(context.draftDirty, false);
  await context.addSource(1);
  assert.equal(context.draft.active_units[0].sources.length, 1);
  assert.equal(context.draft.active_units[0].confirmed, false);
  assert.equal(context.draftDirty, false);
});

test('aggiungere una sorgente preserva la richiesta modificata durante il salvataggio', async () => {
  const context = savedItemFixture(true);
  await context.addSource(1);
  assert.equal(context.draft.request, 'New local edit');
  assert.equal(context.draft.active_units[0].sources.length, 1);
  assert.equal(context.draft.active_units[0].confirmed, false);
  assert.equal(context.draftDirty, true);
});
