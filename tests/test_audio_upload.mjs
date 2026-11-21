import {t, tr, diagnostic, uiLanguage} from '../app/static/i18n.js';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const source=await readFile(new URL('../app/static/audio-upload.js',import.meta.url));
const {applyUploadedAudio}=await import(`data:text/javascript;base64,${source.toString('base64')}`);

test('il file resta associato se si modifica il cut mentre arriva la risposta di caricamento',()=>{
  const original={id:'a1',media_id:null,name:'Mamma',segment_start_s:0,segment_end_s:null,transcript:'',role:'speech',speaker_subject:null};
  const current={...original,name:'Voce della mamma',speaker_subject:4,transcript:'La mia correzione'};
  const uploaded={...original,media_id:'new-file',measured_duration_s:4,sample_rate:24000,sample_count:96000,channels:1,confirmed:false,linked_to_h3:false};
  applyUploadedAudio(current,uploaded,original);
  assert.equal(current.media_id,'new-file');
  assert.equal(current.measured_duration_s,4);
  assert.equal(current.name,'Voce della mamma');
  assert.equal(current.speaker_subject,4);
  assert.equal(current.transcript,'La mia correzione');
  assert.equal(current.confirmed,false);
  assert.equal(current.linked_to_h3,false);
});

test('sostituire il file azzera i vecchi segmenti e parole, conservando le nuove modifiche esplicite',()=>{
  const original={id:'a1',media_id:'old',name:'Traccia',segment_start_s:3,segment_end_s:7,transcript:'Vecchia trascrizione'};
  const current={...original};
  const uploaded={...original,media_id:'new',segment_start_s:0,segment_end_s:null,transcript:'',confirmed:false,linked_to_h3:false};
  applyUploadedAudio(current,uploaded,original);
  assert.equal(current.media_id,'new');
  assert.equal(current.segment_start_s,0);
  assert.equal(current.segment_end_s,null);
  assert.equal(current.transcript,'');
});

const appSource=await readFile(new URL('../app/static/app.js',import.meta.url),'utf8');
const uploadSource=appSource.slice(appSource.indexOf('async function uploadFiles('),appSource.indexOf('async function uploadAudioMedia('));
test('un drop rifiutato non crea tracce vuote; un file valido riempie prima quella già aperta',async()=>{
  const attached=[];let added=0;
  const context={
    draft:{audio_references:[{id:'a8',media_id:null,name:'Mamma'}]},
    uploadAudioMedia:async()=>{throw new Error('Audio non leggibile');},
    addItem:async()=>{added++;},
    uploadAudio:async(...args)=>attached.push(args),
    feedback(){},
  };
  Object.assign(context, {t, tr, diagnostic, uiLanguage});
  vm.createContext(context);
  vm.runInContext(uploadSource,context);
  await assert.rejects(()=>context.uploadFiles('audio',[{name:'bad.mp3'}]),/non leggibile/);
  assert.equal(added,0);
  context.uploadAudioMedia=async()=>({id:'valid-media'});
  await context.uploadFiles('audio',[{name:'mamma.mp3'}]);
  assert.equal(added,0);
  assert.equal(attached[0][0],'a8');
  assert.equal(attached[0][2].id,'valid-media');
});
