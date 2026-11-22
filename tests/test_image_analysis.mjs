import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {selectedAnalysis, setAnalysisChoice, analysisLabel, analysisProposals, renderAnalysisControls} from '../app/static/image-analysis.js';

const options = JSON.parse(readFileSync(new URL('../app/static/image-analysis-options.json', import.meta.url)));

test('il ruolo dimensionale segue il profilo dedicato e mostra un’etichetta leggibile',()=>{
  const picture={role:'scale_reference'};
  const settings=selectedAnalysis(picture,options);
  assert.equal(settings.category,'scale_reference');
  assert.equal(analysisLabel(settings,options),'Riferimento dimensionale · Compact');
  const {box,ui}=fixture(picture);
  assert.ok(box.children.some(child=>child.textContent?.includes('rapporto dimensionale visibile')));
  assert.equal(ui.changes,0);
});
function fixture(picture, config = options) {
  const controls = [];
  const ui = {
    changes:0, opened:0,
    el(tag,className,text) {return {tag,className,text,children:[],setAttribute(){},append(...items){this.children.push(...items);}};},
    field(label,value,change) {const node={label,value,change};controls.push(node);return node;},
    selectField(label,value,choices,change) {const node={label,value,choices,change};controls.push(node);return node;},
    button(text,className,click) {const node={text,click};controls.push(node);return node;},
    changed(){ui.changes++;}, openSubjects(){ui.opened++;}
  };
  return {box:renderAnalysisControls(picture,config,ui), controls, ui};
}

test('i profili seguono il ruolo solo nella modalità automatica e mantengono le guide H3',()=>{
  for(const [role,category] of Object.entries(options.role_categories)) assert.equal(selectedAnalysis({role},options).category,category);
  assert.equal(selectedAnalysis({role:'spatial_map'},options).category,'spatial_map');
  assert.equal(selectedAnalysis({role:'identity',analysis:{category:'clothing',level:'full'}},options).category,'clothing');
  assert.equal(selectedAnalysis({role:'identity'},options).level,'compact');
});

test('cambiare categoria e livello conserva testo manuale, ruolo e conferma, senza chiamate',()=>{
  const picture={role:'outfit',description_en:'My exact description.',confirmed:true};
  const {controls,ui}=fixture(picture);
  controls.find(c=>c.label==='Categoria di analisi').change('accessory');
  controls.find(c=>c.label==='Livello di descrizione').change('full');
  controls.find(c=>c.label?.startsWith('Attributo o dettaglio')).change('fibbia');
  controls.find(c=>c.label?.startsWith('Vista dell’immagine')).change('back');
  assert.deepEqual(picture.analysis,{category:'accessory',level:'full',attribute:'fibbia',view:'back'});
  assert.equal(picture.role,'outfit');assert.equal(picture.description_en,'My exact description.');assert.equal(picture.confirmed,true);
  assert.equal(ui.changes,4);
});

test('ripristinare i default elimina il campo additivo e conserva i vecchi input',()=>{
  const picture={role:'identity'};
  setAnalysisChoice(picture,'level','full');setAnalysisChoice(picture,'level','compact');
  assert.deepEqual(picture,{role:'identity'});
  assert.deepEqual(options.levels.map(c=>c.value),['compact','medium','full']);
});

test('body mark e replacement aprono i Subject senza crearli o associare immagini',()=>{
  const picture={role:'object'};
  const {controls,box,ui}=fixture(picture);
  const shortcut=controls.find(c=>c.text==='Apri i dettagli fisici nei Subject');
  assert.equal(shortcut.hidden,true);
  controls.find(c=>c.label==='Categoria di analisi').change('replacement');
  assert.equal(shortcut.hidden,false);
  assert.match(box.children.find(c=>c.className==='field-help').textContent,/Sostituzione/);
  shortcut.click();assert.equal(ui.opened,1);
  assert.deepEqual(picture,{role:'object',analysis:{category:'replacement'}});
});

test('la proposta identifica categoria, livello e vista; i controlli attendono il catalogo',()=>{
  assert.match(analysisLabel({category:'clothing',level:'medium',view:'back'},options),/Abbigliamento.*Medium.*Retro/);
  const {box,controls}=fixture({role:'identity'},null);
  assert.equal(controls.length,0);assert.match(box.children[1].text,/Caricamento/);
});

test('le varianti sono distinte e cambiare categoria conserva i lavori attivi annullabili',()=>{
  const config={category:'clothing',level:'compact',attribute:'',view:''};
  const job=(id,analysis,status='succeeded',kind='image_analyze')=>({id,kind,status,analysis});
  const jobs=[job('old',config),job('compact',config),job('full',{...config,level:'full'}),
    job('other',{...config,category:'replacement'}),job('pending',{...config,category:'replacement'},'running'),
    job('translate',undefined,'succeeded','description_translate')];
  assert.deepEqual(analysisProposals(jobs,{role:'outfit'},options).map(j=>j.id),['compact','full','pending','translate']);
  assert.deepEqual(analysisProposals(jobs,{role:'outfit',analysis:{category:'replacement'}},options).map(j=>j.id),['pending','translate']);
  assert.match(analysisLabel({...config,attribute:'fibbia'},options),/fibbia/);
});

test('il singolo comando Analizza usa la scelta visibile, senza inferenze al cambio di tipo',async()=>{
  const source=readFileSync(new URL('../app/static/app.js',import.meta.url),'utf8');
  const handler=source.slice(source.indexOf('const analysisState = pictureDescriptionState(picture);'),source.indexOf("const profile=el('p','field-help');"));
  const actions=[],selectors=[],sent=[],state={mode:'image_analyze'};
  const c={picture:{id:'picture',description_language:'English'},pictureDescriptionState:()=>state,language:{},
    el:()=>({append(){}}),t:v=>v,refreshAssistancePanels(){},updateAssistanceControls(){},
    selectField:(label,value,choices,change)=>{const field={label,value,choices,change,dataset:{}};selectors.push(field);return field;},
    serverButton:(text,click)=>{const button={text,click,dataset:{}};actions.push(button);return button;},
    requestAssistance:async(...args)=>sent.push(args)};
  vm.createContext(c);vm.runInContext(handler,c);
  assert.equal(actions.filter(b=>b.text==='Analizza').length,1);
  for(const kind of ['image_character_sheet','image_analyze']){
    const before=sent.length;selectors[0].change(kind);assert.equal(sent.length,before);
    await actions.find(b=>b.text==='Analizza').click();assert.deepEqual(sent.at(-1),[kind,'picture',true]);
  }
  assert.equal(actions.find(b=>b.text==='Traduci in inglese').hidden,true);
});
