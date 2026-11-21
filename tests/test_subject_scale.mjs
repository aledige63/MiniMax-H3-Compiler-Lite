import assert from 'node:assert/strict';
import test from 'node:test';
import {renderSubjectScale,updateScale} from '../app/static/subject-scale.js';
import {unitPictureIds,visibleReferenceTokens,associatePicture} from '../app/static/reference-menu.js';

function fixture(unit, units=[unit], pictures=[], ids={}) {
  const controls=[];
  const ui={changes:0,redraws:0,
    el(tag,className,text) {return {tag,className,text,children:[],append(...items){this.children.push(...items);}};},
    field(label,value,change) {const node={label,value,change};controls.push(node);return node;},
    selectField(label,value,choices,change) {const node={label,value,choices,change};controls.push(node);return node;},
    button(text,className,click) {const node={text,click};controls.push(node);return node;},
    changed(){ui.changes++;},redraw(){ui.redraws++;},
  };
  const section=renderSubjectScale(unit,units,pictures,ids,ui);
  return {controls,section,ui};
}

test('aprire la sezione non cambia la bozza, le modifiche sono locali e richiedono conferma',()=>{
  const unit={subject:2,confirmed:true,sources:[{picture_id:'photo',attribute:'object'}]};
  const original=structuredClone(unit);const view=fixture(unit);
  assert.equal(view.section.open,false);assert.deepEqual(unit,original);
  view.controls.find(c=>c.label==='Misure · facoltative').change('altezza 20 cm');
  assert.equal(unit.scale.measurements,'altezza 20 cm');assert.equal(unit.confirmed,false);
  assert.deepEqual(unit.sources,original.sources);
  view.controls.find(c=>c.label==='Confronto dimensionale').change('si tiene con una mano');
  assert.equal(unit.scale.comparison,'si tiene con una mano');
  assert.equal(view.ui.redraws,0);
});

test('la stessa Picture serve per oggetto e scala occupando una sola dipendenza',()=>{
  const unit={subject:2,sources:[{picture_id:'photo',attribute:'object'}]};
  const photo={id:'photo',slot:5,role:'object',name:'Bottiglia',description_en:'a blue bottle',confirmed:true,linked_to_h3:true};
  const view=fixture(unit,[unit],[photo]);
  view.controls.find(c=>c.label==='Picture di riferimento dimensionale · facoltativa').change('photo');
  assert.equal(unit.scale.picture_id,'photo');assert.deepEqual(unitPictureIds(unit),['photo']);
  assert.equal(view.ui.redraws,1);
  const tokens=visibleReferenceTokens([{id:'photo',kind:'picture',token:'<Picture 5>'}],{active_units:[unit],pictures:[photo]});
  assert.equal(tokens[0].requiresAssociation,false);
});

test('il confronto conserva UUID e numero locale, esclude se stesso e i Subject disattivi',()=>{
  const unit={subject:2}, other={subject:7,name:'Ann'}, excluded={subject:4,name:'Escluso',excluded:true};
  const view=fixture(unit,[unit,other,excluded],[],{'2':'bottle-id','7':'person-id','4':'excluded-id'});
  const menu=view.controls.find(c=>c.label==='Subject di confronto · facoltativo');
  assert.deepEqual(menu.choices.map(([id])=>id),['','person-id']);
  menu.change('person-id');
  assert.equal(unit.scale.reference_subject_id,'person-id');assert.equal(unit.scale.reference_subject,7);
  menu.change('');assert.equal(unit.scale,undefined);
});

test('riferimenti rimossi o esclusi restano recuperabili senza sostituzioni automatiche',()=>{
  const unit={subject:2,scale:{comparison:'come nella foto',reference_subject_id:'missing',reference_subject:9,picture_id:'gone'}};
  const original=structuredClone(unit);
  const view=fixture(unit,[unit],[{id:'guide',role:'style'},{id:'excluded',excluded:true}]);
  assert.equal(view.controls.find(c=>c.label==='Subject di confronto · facoltativo').value,'missing');
  const images=view.controls.find(c=>c.label==='Picture di riferimento dimensionale · facoltativa');
  assert.equal(images.value,'gone');assert.deepEqual(images.choices.map(([id])=>id),['','gone']);
  assert.deepEqual(unit,original);
  view.controls.find(c=>c.text==='Rimuovi dimensioni e scala').click();
  assert.equal(unit.scale,undefined);assert.equal(unit.confirmed,false);
});

test('svuotare i soli campi testuali rimuove il default senza perdere gli altri attributi',()=>{
  const unit={subject:1,scale:{measurements:'20 cm'},confirmed:true};
  updateScale(unit,{measurements:''});
  assert.equal(unit.scale,undefined);assert.equal(unit.subject,1);assert.equal(unit.confirmed,false);
});

test('il ruolo dimensionale è selezionabile per la scala ma non come sorgente di aspetto',()=>{
  const unit={subject:3,sources:[{picture_id:'object',attribute:'object'}]};
  const photo={id:'dimension',slot:4,role:'scale_reference',name:'Referenza',description_en:'a bottle held in one hand',confirmed:true,linked_to_h3:true};
  const view=fixture(unit,[unit],[photo]);
  const menu=view.controls.find(c=>c.label==='Picture di riferimento dimensionale · facoltativa');
  assert.equal(menu.choices.some(([id])=>id===photo.id),true);
  const tokens=[{id:photo.id,kind:'picture',token:'<Picture 4>'}];
  const draft={active_units:[unit],pictures:[photo]};
  assert.deepEqual(visibleReferenceTokens(tokens,draft),[]);
  menu.change(photo.id);
  const selected=visibleReferenceTokens(tokens,draft);
  assert.equal(selected.length,1);assert.equal(selected[0].requiresAssociation,false);
  assert.match(selected[0].label,/riferimento dimensionale/);
  assert.throws(()=>associatePicture(draft,photo.id,3,'object'));
  assert.deepEqual(unit.sources,[{picture_id:'object',attribute:'object'}]);
});
