import {t, tr, diagnostic, uiLanguage} from '../app/static/i18n.js';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import test from 'node:test';

const source=await readFile(new URL('../app/static/app.js',import.meta.url),'utf8');
const purgeSource=source.slice(source.indexOf('async function purgeArchive('),source.indexOf("$('export-archive').onclick",source.indexOf('async function purgeArchive(')));

function fixture() {
  const dialogs=[],requests=[],waiting=[];
  const element=(tag,className,text)=>({tag,className,text,children:[],append(...children){this.children.push(...children);}});
  const input=()=>({querySelector:()=>({})});
  const plan={labels:['Progetto di prova'],projects:1,scenes:1,cuts:1,versions:0,files_to_remove:0,media_retained:0,warnings:[],blockers:[],plan_hash:'fixture'};
  const context={workspace:{id:'active-cut'},el:element,field:input,checkbox:input,newCommandId:()=> 'test-command',
    closeCurrentDialog(){},preserveEdits:async()=>{},refreshProjects:async()=>{},findCut:()=>true,
    renderNavigation(){},feedback(message){context.feedbackMessage=message;},
    dialog(title,content,submit){
      dialogs.push({title,content,submit});
      return new Promise(resolve=>{waiting.push(resolve);context.closeCurrentDialog=()=>resolve(false);});
    },
    async request(path,options){requests.push({path,body:JSON.parse(options.body)});return path.endsWith('/preview')?plan:{pending_files:0};}
  };
  Object.assign(context, {t, tr, diagnostic, uiLanguage});
  vm.createContext(context);vm.runInContext(purgeSource,context);
  return {context,dialogs,requests,waiting,plan};
}

const flush=()=>new Promise(resolve=>setImmediate(resolve));

test('un errore nel salvataggio preliminare resta visibile e non avvia cancellazioni',async()=>{
  const f=fixture();f.context.preserveEdits=async()=>{throw new Error('Conserva i campi locali: il riferimento è cambiato.');};
  const work=f.context.purgeArchive({scope:'trash'});
  assert.equal(f.dialogs[0].title,'Preparazione del cestino');
  await flush();
  assert.equal(f.dialogs[1].title,'Anteprima del cestino non disponibile');
  assert.match(f.dialogs[1].content.text,/Conserva i campi locali/);
  assert.equal(f.requests.length,0);
  f.waiting[1](false);await work;
});

test('una richiesta di anteprima fallita mostra l’errore nella finestra',async()=>{
  const f=fixture();f.context.request=async path=>{f.requests.push({path});throw new Error('Sessione scaduta. Accedi di nuovo.');};
  const work=f.context.purgeArchive({scope:'trash'});await flush();
  assert.equal(f.dialogs[1].title,'Anteprima del cestino non disponibile');
  assert.match(f.dialogs[1].content.text,/Sessione scaduta/);
  assert.deepEqual(f.requests.map(r=>r.path),['/api/trash/preview']);
  f.waiting[1](false);await work;
});

test('annullare durante il caricamento impedisce a una risposta tardiva di riaprire la conferma',async()=>{
  const f=fixture();let finishPreview;
  f.context.request=path=>{f.requests.push({path});return new Promise(resolve=>{finishPreview=resolve;});};
  const work=f.context.purgeArchive({scope:'trash'});await flush();
  f.context.closeCurrentDialog();await flush();finishPreview(f.plan);await work;
  assert.equal(f.dialogs.length,1);
  assert.deepEqual(f.requests.map(r=>r.path),['/api/trash/preview']);
});

test('lo svuotamento richiede ancora la conferma e i blocchi non possono inviare il comando',async()=>{
  for(const blocked of [false,true]){
    const f=fixture();if(blocked)f.plan.blockers.push('Un cut conserva un collegamento.');
    const work=f.context.purgeArchive({scope:'trash'});await flush();
    assert.equal(f.dialogs[1].title,blocked?'Cancellazione non disponibile':'Elimina definitivamente');
    f.waiting[1](false);await work;
    assert.deepEqual(f.requests.map(r=>r.path),['/api/trash/preview']);
  }
});

test('gli errori dopo la conferma rimangono visibili senza dichiarare riuscita la cancellazione',async()=>{
  for(const network of [false,true]){
    const f=fixture();const request=f.context.request;
    f.context.request=async(path,options)=>{
      if(path.endsWith('/preview'))return request(path,options);
      f.requests.push({path});const error=new Error(network?'Esito non ricevuto.':'Il contenuto del cestino è cambiato.');
      error.code=network?'network':'purge_stale';throw error;
    };
    const work=f.context.purgeArchive({scope:'trash'});await flush();f.waiting[1](true);await flush();
    assert.equal(f.dialogs[2].title,'Problema durante la cancellazione');
    assert.equal(f.dialogs[2].content.children.some(node=>/verificare gli elementi rimasti/.test(node.text)),network);
    assert.equal(f.context.feedbackMessage,undefined);
    f.waiting[2](false);await work;
  }
});

test('un comando confermato usa lo stesso piano e aggiorna l’elenco senza una seconda cancellazione',async()=>{
  const f=fixture();let refreshed=0;f.context.refreshProjects=async()=>{refreshed++;};
  const work=f.context.purgeArchive({scope:'trash'});await flush();f.waiting[1](true);await work;
  assert.equal(refreshed,1);assert.match(f.context.feedbackMessage,/eliminati/);
  assert.deepEqual(f.requests.map(r=>r.path),['/api/trash/preview','/api/trash/purge']);
  assert.deepEqual(f.requests[1].body,{command_id:'test-command',selection:{scope:'trash'},plan_hash:'fixture',confirmed:true,confirmation:'ELIMINA'});
});

test('una nuova finestra non eredita il pulsante disabilitato dall’esportazione',async()=>{
  const nodes={'action-dialog':{showModal(){},close(){}},'dialog-title':{},'dialog-content':{replaceChildren(){}},'dialog-error':{},
    'dialog-submit':{disabled:true},'dialog-form':{},'dialog-cancel':{}};
  const context={$:id=>nodes[id],closeCurrentDialog(){}};
  Object.assign(context, {t, tr, diagnostic, uiLanguage});
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function dialog('),source.indexOf('async function askName(')),context);
  const pending=context.dialog('Elimina definitivamente',{},'Elimina definitivamente');
  assert.equal(nodes['dialog-submit'].disabled,false);
  context.closeCurrentDialog();assert.equal(await pending,false);
});
