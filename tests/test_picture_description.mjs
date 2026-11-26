import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {pictureProposalView,renderPictureProposals,pictureTaskLabel} from '../app/static/picture-description.js';
import {setUiLanguage} from '../app/static/i18n.js';
import vm from 'node:vm';

const options=JSON.parse(readFileSync(new URL('../app/static/image-analysis-options.json',import.meta.url)));
const picture={id:'picture',role:'identity',description_en:'Current manual text.'};
const analysis={category:'character',level:'compact',attribute:'',view:''};
const job=(id,extra={})=>({id,target_id:'picture',kind:'image_character_sheet',status:'succeeded',analysis,
  result:{text:'An exact proposed description.\n',warnings:[],metrics:{cache_hit:true}},...extra});

test('le schede oggetto partecipano alla proposta unica e allo storico di tre risultati',()=>{
  const object={...picture,role:'object'};
  const jobs=[job('old'),job('single',{kind:'image_analyze',analysis:{...analysis,category:'held_item'}}),
    job('object',{kind:'image_object_sheet',analysis:{...analysis,category:'held_item'}})];
  const current=pictureProposalView(jobs,object,options,'image_object_sheet');
  assert.equal(current.current.id,'object');
  assert.deepEqual(current.history.map(j=>j.id),['single','old']);
  assert.equal(pictureProposalView(jobs,object,options,'image_analyze').current,null);
  jobs.at(-1).discarded=true;
  assert.equal(pictureProposalView(jobs,object,options,'image_object_sheet').current,null);
  setUiLanguage('en');
  try{assert.equal(pictureTaskLabel('image_object_sheet'),'Object sheet · multiple views');}
  finally{setUiLanguage('it');}
});

test('one latest matching proposal is current; legacy and other profiles stay in history',()=>{
  const jobs=[job('legacy',{analysis:null}),job('medium',{analysis:{...analysis,level:'medium'}}),job('latest')];
  const view=pictureProposalView(jobs,picture,options,'image_character_sheet');
  assert.equal(view.current.id,'latest');assert.deepEqual(view.history.map(j=>j.id),['medium','legacy']);
  assert.equal(jobs.length,3);
});

test('discarding or applying the latest result never promotes an older proposal',()=>{
  for(const flag of ['discarded','applied','stale']){
    const jobs=[job('old'),job('latest',{[flag]:true})];
    const view=pictureProposalView(jobs,picture,options,'image_character_sheet');
    assert.equal(view.current,null);assert.deepEqual(view.history.map(j=>j.id),['latest','old']);
  }
});

test('a selected task and every profile field determine which result is current',()=>{
  assert.equal(pictureProposalView([job('image',{kind:'image_analyze'})],picture,options,'image_character_sheet').current,null);
  for(const [key,value] of [['level','full'],['category','clothing'],['attribute','hair'],['view','back']]){
    const updated={...picture,analysis:{[key]:value}};
    assert.equal(pictureProposalView([job('old')],updated,options,'image_character_sheet').current,null,key);
  }
});

test('pending work remains visible and cancellable after a local profile change',()=>{
  const jobs=[job('pending',{status:'running'}),job('later',{discarded:true})];
  const view=pictureProposalView(jobs,{...picture,analysis:{level:'full'}},options,'image_analyze');
  assert.equal(view.current.id,'pending');assert.equal(view.history.length,1);
});

test('an error stays current instead of falling back to an old successful proposal',()=>{
  const failed=job('failed',{status:'failed',result:{text:null,issues:['Visible error.']}});
  assert.equal(pictureProposalView([job('old'),failed],picture,options,'image_character_sheet').current.id,'failed');
});

class Node {
  constructor(tag,className='',text=''){Object.assign(this,{tag,className,text,children:[],events:{},dataset:{}});}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  addEventListener(name,callback){this.events[name]=callback;}
  setAttribute(name,value){this[name]=value;}
}
const flatten=node=>[node,...node.children.flatMap(flatten)];
function render(jobs,overrides={}){
  const panel=new Node('div'),calls=[],state={historyOpen:false};
  const ui={el:(...args)=>new Node(...args),serverButton:(text,click)=>Object.assign(new Node('button','',text),{click}),
    apply:j=>calls.push(['apply',j.id]),dismiss:j=>calls.push(['dismiss',j.id]),cancel:j=>calls.push(['cancel',j.id]),
    diagnostic:v=>v,canApply:()=>true,locked:false,error:j=>j.result.issues.join(' '),...overrides};
  renderPictureProposals(panel,picture,jobs,'image_character_sheet',options,state,ui);
  return {panel,calls,state,nodes:flatten(panel)};
}

test('rendering exposes one exact proposal, use/discard actions and a closed read-only history',()=>{
  const r=render([job('old',{stale:true}),job('new')]);
  assert.equal(r.nodes.filter(n=>n.className==='description-proposal').length,1);
  const history=r.nodes.find(n=>n.className==='description-history');assert.equal(history.open,false);
  assert.equal(r.nodes.filter(n=>n.tag==='button').length,2);
  r.nodes.find(n=>n.text==='Scarta').click();assert.deepEqual(r.calls,[['dismiss','new']]);
  assert.equal(r.nodes.find(n=>n.className==='proposed-description').text,'An exact proposed description.\n');
  history.open=true;history.events.toggle();assert.equal(r.state.historyOpen,true);
  assert.equal(r.calls.length,1); // Opening history never issues a request.
});

test('discarded history preserves text and warnings without application or retry buttons',()=>{
  const r=render([job('old',{discarded:true,result:{text:'Exact historical text.',warnings:['Historical warning.']}})]);
  assert.equal(r.nodes.some(n=>n.className==='description-proposal'),false);
  assert.equal(r.nodes.filter(n=>n.tag==='button').length,0);
  assert.ok(r.nodes.some(n=>n.text==='Exact historical text.'));
  assert.ok(r.nodes.some(n=>n.text==='Historical warning.'));
});

test('local unsaved edits and scene locks disable use without losing the proposal',()=>{
  const r=render([job('new')],{canApply:()=>false,locked:true});
  assert.equal(r.nodes.find(n=>n.text==='Usa questa descrizione').disabled,true);
  assert.equal(r.nodes.find(n=>n.text==='Scarta').disabled,true);
  assert.ok(r.nodes.some(n=>n.text==='An exact proposed description.\n'));
});

test('English uses the same single-proposal workflow and preserves user text',()=>{
  setUiLanguage('en');
  try{
    const r=render([job('new')]);
    assert.ok(r.nodes.some(n=>n.text==='Proposal to review'));
    assert.ok(r.nodes.some(n=>n.text==='Use this description'));
    assert.ok(r.nodes.some(n=>n.text==='Discard'));
    assert.ok(r.nodes.some(n=>n.text==='An exact proposed description.\n'));
  }finally{setUiLanguage('it');}
});

test('only the newest three image results are exposed, including the current proposal',()=>{
  const jobs=Array.from({length:8},(_,i)=>job(String(i)));
  const view=pictureProposalView(jobs,picture,options,'image_character_sheet');
  assert.equal(view.current.id,'7');assert.deepEqual(view.history.map(j=>j.id),['6','5']);
});

test('the current proposal disappears immediately while discard is being saved',()=>{
  const panel=new Node('div'),state={pendingDismiss:new Set(['new']),notice:'Discarding…'};
  renderPictureProposals(panel,picture,[job('new')],'image_character_sheet',options,state,
    {el:(...args)=>new Node(...args),serverButton:()=>new Node('button'),diagnostic:v=>v,canApply:()=>true});
  assert.equal(flatten(panel).some(n=>n.className==='description-proposal'),false);
  assert.ok(flatten(panel).some(n=>n.text==='Discarding…'));
});

test('the real discard handler hides before the response and restores the proposal on an error',async()=>{
  const source=readFileSync(new URL('../app/static/app.js',import.meta.url),'utf8');
  const handler=source.slice(source.indexOf('async function dismissAssistance('),source.indexOf('function enableDrop('));
  for(const fail of [false,true]){
    const state={},frames=[];let release;
    const c={workspace:{id:'cut',revision:1},draft:{pictures:[picture]},document:{querySelectorAll:()=>[]},Set,t:v=>v,newCommandId:()=> 'discard',
      pictureDescriptionState:()=>state,updateButtons(){},feedback(){},
      refreshAssistancePanels:()=>frames.push({hidden:state.pendingDismiss?.has('new'),notice:state.notice}),
      mutation:async(method,url,body,apply)=>{await new Promise(resolve=>release=resolve);if(fail)throw Error('save failed');apply({id:'cut',revision:2});}};
    vm.createContext(c);vm.runInContext(handler,c);
    const request=c.dismissAssistance(job('new'));
    assert.equal(frames[0].hidden,true);assert.match(frames[0].notice,/in corso/);
    release();if(fail)await assert.rejects(request,/save failed/);else await request;
    assert.equal(state.pendingDismiss.size,0);
    assert.equal(state.noticeError,fail);
    if(fail)assert.match(state.notice,/save failed/);else assert.equal(c.workspace.revision,2);
  }
});

test('an older polling response cannot resurrect a proposal after discard',()=>{
  const source=readFileSync(new URL('../app/static/app.js',import.meta.url),'utf8');
  const handler=source.slice(source.indexOf('function mergePolledView('),source.indexOf('function startAssistancePolling('));
  const workspace={id:'cut',revision:5,assistance_jobs:[job('new',{discarded:true})]};
  const c={workspace,t:v=>v,$:()=>({}),localError:null};vm.createContext(c);vm.runInContext(handler,c);
  c.mergePolledView({id:'cut',revision:4,assistance_jobs:[job('new')]});
  assert.equal(c.workspace,workspace);assert.equal(c.workspace.assistance_jobs[0].discarded,true);
});
