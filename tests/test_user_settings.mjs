import assert from 'node:assert/strict';
import test from 'node:test';
import {createUserSettings, serviceFor, modelLabel, eligibleModels} from '../app/static/user-settings.js';

function fixture() {
  const nodes = new Map();
  const document = {getElementById(id) {
    if (!nodes.has(id)) nodes.set(id, {value:'',checked:false,disabled:false,hidden:false,textContent:'',classList:{toggle(){}}});
    return nodes.get(id);
  }};
  const calls = [], changes = [];
  let reloads = 0;
  const request = async (path, options) => {
    calls.push({path, body:options?.body ? JSON.parse(options.body) : undefined});
    if (path === '/api/access/status') return {enabled:false,configured:false,local:false,protect_all:true};
    if (path === '/api/access/settings') return {csrf:'new-csrf',enabled:true};
    if (path.startsWith('/api/connections/models/')) return [{name:'selected'}];
    return {revision:1,ollama_url:'http://private-server:11434',timeout_s:120,openai_key_set:true};
  };
  const api = createUserSettings(document, {request:(...args)=>fixtureState.request(...args),commandId:()=> 'command-id',
    reloadModels:async()=> {reloads++;},accessChanged:async value=>changes.push(value)});
  const fixtureState = {api,nodes,$:document.getElementById.bind(document),calls,changes,request,get reloads(){return reloads;}};
  return fixtureState;
}

test('i modelli omonimi sono filtrati dal servizio e conservano identità distinte',()=>{
  const models = [{name:'same',capabilities:['completion','vision']},{name:'openai::same',capabilities:['completion','vision']}];
  assert.equal(serviceFor('openai::same'),'openai');
  assert.deepEqual(eligibleModels(models,'ollama','vision').map(m=>m.name),['same']);
  assert.deepEqual(eligibleModels(models,'openai','completion').map(m=>m.name),['openai::same']);
  assert.equal(modelLabel(models[1]),'OpenAI · same');
});

test('caricare le impostazioni non rivela la chiave e non avvia prove',async()=>{
  const f=fixture();await f.api.load();
  assert.equal(f.$('ollama-url').value,'http://private-server:11434');
  assert.equal(f.$('openai-key').value,'');
  assert.match(f.$('openai-key-state').textContent,/salvata/);
  assert.ok(f.calls.every(call=>!call.body));
});

test('connetti salva la scelta, aggiorna la lista e cancella il campo chiave senza inferenze',async()=>{
  const f=fixture();await f.api.load();f.calls.length=0;
  f.$('openai-key').value='new-test-key';
  await f.$('connect-openai').onclick();
  assert.equal(f.calls[0].body.api_key,'new-test-key');
  assert.equal(f.calls[1].path,'/api/connections/models/openai');
  assert.equal(f.$('openai-key').value,'');
  assert.equal(f.reloads,1);
  assert.ok(f.calls.every(call=>!call.path.includes('trials')));
});

test('un errore di salvataggio conserva i valori e rende il pulsante riutilizzabile',async()=>{
  const f=fixture();await f.api.load();
  f.$('ollama-url').value='http://new-server:11434';f.$('openai-key').value='new-test-key';
  f.request=async()=> {throw new Error('Attendi il lavoro in coda.');};
  await f.$('save-connections').onclick();
  assert.equal(f.$('ollama-url').value,'http://new-server:11434');
  assert.equal(f.$('openai-key').value,'new-test-key');
  assert.match(f.$('connections-status').textContent,/coda/);
  assert.equal(f.$('save-connections').disabled,false);
});

test('password diverse o troppo corte non vengono inviate e non cambiano l’accesso',async()=>{
  const f=fixture();await f.api.load();f.calls.length=0;
  f.$('access-enabled').checked=true;f.$('new-password').value='long-password-value';
  f.$('confirm-password').value='different-password';
  await f.$('save-access').onclick();
  assert.match(f.$('access-status').textContent,/non coincidono/);
  assert.equal(f.calls.length,0);assert.equal(f.changes.length,0);
});

test('la password attuale accompagna la modifica e il nuovo csrf viene applicato prima di ricaricare',async()=>{
  const f=fixture();await f.api.load();f.calls.length=0;
  f.$('access-enabled').checked=true;f.$('current-password').value='old-password-value';
  f.$('new-password').value=f.$('confirm-password').value='new-password-value';
  await f.$('save-access').onclick();
  assert.deepEqual(f.calls[0].body,{enabled:true,current_password:'old-password-value',password:'new-password-value'});
  assert.equal(f.changes[0].csrf,'new-csrf');
  assert.equal(f.$('current-password').value,'');assert.equal(f.$('new-password').value,'');
});
