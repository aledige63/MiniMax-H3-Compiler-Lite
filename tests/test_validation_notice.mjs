import {t, tr, diagnostic, uiLanguage} from '../app/static/i18n.js';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import test from 'node:test';

const source=await readFile(new URL('../app/static/app.js',import.meta.url),'utf8');
const noticeSource=source.slice(source.indexOf('function renderNotice()'),source.indexOf('function renderResults()'));

function noticeFixture(workspace, extra={}) {
  const nodes=Object.fromEntries(['notice','notice-title','notice-body','notice-issues'].map(id=>[id,{classList:{add(){}},textContent:''}]));
  const context={workspace,localError:null,compileFailure:null,draftDirty:false,$:id=>nodes[id],
    activeJob:()=>false,displayedProposal:()=>null,showIssues:(node,issues)=>{node.issues=Array.from(issues);},...extra};
  Object.assign(context, {t, tr, diagnostic, uiLanguage});
  vm.runInNewContext(noticeSource+';renderNotice();',context);
  return nodes;
}

test('le conferme mancanti della bozza attuale precedono gli errori di compilazioni passate',()=>{
  const issue='Subject 4 · Mamma — spunta «Confermo definizione e associazioni di questo Subject».';
  const nodes=noticeFixture({catalogue_issues:[issue],latest_job:{status:'failed',stale:true,result:{status:'error',issues:['Errore precedente']}}});
  assert.equal(nodes['notice-title'].textContent,'Controlli da completare');
  assert.deepEqual(nodes['notice-issues'].issues,[issue]);
  assert.doesNotMatch(nodes['notice-body'].textContent,/Errore precedente/);
});

test('le modifiche locali rendono esplicito che la lista deriva dall’ultimo controllo salvato',()=>{
  const nodes=noticeFixture({catalogue_issues:['Conferma mancante']},{draftDirty:true});
  assert.equal(nodes['notice-title'].textContent,'Modifiche da verificare');
  assert.match(nodes['notice-body'].textContent,/ultimo controllo/);
});

test('un rifiuto strutturale del modello è distinto dai campi mancanti e dagli errori obsoleti',()=>{
  const latest_job={status:'failed',result:{status:'error',error_code:'invalid_structure',issues:['Manca il marcatore della battuta d2.']}};
  const nodes=noticeFixture({latest_job});
  assert.equal(nodes['notice-title'].textContent,'Risposta del modello non valida');
  assert.equal(nodes['notice-body'].textContent,'Manca il marcatore della battuta d2.');
  assert.deepEqual(nodes['notice-issues'].issues,[]);
  for(const extra of [{draftDirty:true},{}]){
    const old=noticeFixture({latest_job:{...latest_job,stale:!extra.draftDirty}},extra);
    assert.equal(old['notice-title'].textContent,'Errore di una bozza precedente');
    assert.match(old['notice-body'].textContent,/Ricompila/);
  }
});

test('un blocco operativo mantiene il proprio motivo anche quando ci sono campi da completare',()=>{
  const nodes=noticeFixture({catalogue_issues:['Spunta mancante']},{localError:{title:'Il salvataggio sul Mac è cambiato',message:'Ricarica la bozza prima di salvare.'}});
  assert.equal(nodes['notice-title'].textContent,'Il salvataggio sul Mac è cambiato');
  assert.equal(nodes['notice-body'].textContent,'Ricarica la bozza prima di salvare.');
});

test('la risposta API conserva codice e lista dei controlli specifici',async()=>{
  const requestSource=source.slice(source.indexOf('class ApiError'),source.indexOf('async function mutation('));
  const context={csrf:null,showLogin(){},fetch:async()=>({ok:false,status:422,json:async()=>({detail:{code:'incomplete_input',message:'Completa la battuta.',issues:['Battuta d1 — spunta la conferma.']}})})};
  Object.assign(context, {t, tr, diagnostic, uiLanguage});
  vm.runInNewContext(requestSource+';globalThis.callRequest=request;',context);
  await assert.rejects(context.callRequest('/api/cuts/cut/compile'),error=>{
    assert.equal(error.code,'incomplete_input');
    assert.deepEqual(Array.from(error.issues),['Battuta d1 — spunta la conferma.']);
    return true;
  });
});
