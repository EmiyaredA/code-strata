import test from 'node:test';
import assert from 'node:assert/strict';
import { restoreTabs, closeTab, elementEvidence, selectionFiles, requestGate, sequenceProjection, umlProjection, freshnessText } from '../src/uml-model.js';

test('closing project tabs keeps documents available and restores per-project order',()=>{
  const catalog=[{id:'a'},{id:'b'},{id:'c'}];
  const restored=restoreTabs({tabs:['c','a','c','gone','b'],active:'a'},catalog);
  assert.deepEqual(restored,{tabs:['c','a','b'],active:'a'});
  assert.deepEqual(closeTab(restored,'a'),{tabs:['c','b'],active:'b'});
  assert.equal(catalog.length,3);
  assert.deepEqual(restoreTabs({tabs:[],active:null},catalog),{tabs:[],active:null});
  assert.deepEqual(restoreTabs(restored,[{id:'c'}]),{tabs:['c'],active:'c'});
});
test('edge evidence preserves call and definition locations and highlights all source files',()=>{
  const a={id:'a',evidence:[{id:'def',path:'a.py',startLine:4,locationKind:'definition'}]};
  const b={id:'b',evidence:[{id:'bdef',path:'b.py',startLine:11,locationKind:'definition'}]};
  const edge={source:'a',target:'b',evidence:[{id:'call',path:'a.py',startLine:42,locationKind:'call'}]};
  assert.deepEqual(selectionFiles({nodes:[a,b]},edge),['a.py','b.py']);
  assert.deepEqual(elementEvidence({nodes:[a,b]},edge).map(r=>r.startLine),[42,4,11]);
});
test('source and project request gates reject late resolution after selection, close or project change',async()=>{
  const gate=requestGate();let resolve,visible='';
  const first=gate.next();const pending=new Promise(r=>{resolve=r;}).then(v=>{if(gate.current(first))visible=v;});
  gate.invalidate();const second=gate.next();if(gate.current(second))visible='new source';
  resolve('old source');await pending;assert.equal(visible,'new source');
  gate.invalidate();assert.equal(gate.current(second),false);
});
test('sequence messages preserve sorted order and separate per-message lifeline locations',()=>{
  const model={nodes:[{id:'a'},{id:'b'}],edges:[{id:'late',source:'b',target:'a',role:'return',order:9},{id:'early',source:'a',target:'b',order:2}]};
  const projected=sequenceProjection(model);
  assert.deepEqual(projected.edges.map(e=>e.id),['early','late']);
  assert.equal(projected.edges[0].sourceHandle,'early-out');
  assert.equal(projected.edges[1].targetHandle,'late-in');
  assert.ok(projected.nodes[1].position.x>projected.nodes[0].position.x);
  assert.ok(projected.nodes.every(n=>n.height>=280));
});
test('ELK layouts support branch paths and compound containers without changing semantic edges',async()=>{
  const model={type:'activity',nodes:[{id:'start',role:'start'},{id:'lock',role:'action'},{id:'backup',role:'action'},{id:'unchanged',role:'decision'},{id:'publish',role:'action'}],edges:[['start','lock'],['lock','backup'],['backup','unchanged'],['unchanged','publish']].map(([source,target],i)=>({id:String(i),source,target}))};
  const projection=await umlProjection(model);
  assert.deepEqual(projection.edges.map(e=>[e.id,e.source,e.target]),model.edges.map(e=>[e.id,e.source,e.target]));
  assert.equal(projection.edges[2].sourceHandle,"bottom");
  assert.equal(projection.edges[3].sourceHandle,"left-out");
  for(const n of projection.nodes)assert.ok(Number.isFinite(n.position.x)&&Number.isFinite(n.position.y));
  const nested=await umlProjection({type:'deployment',nodes:[{id:'device',role:'device'},{id:'artifact',role:'artifact',parentId:'device'}],edges:[]});
  assert.equal(nested.nodes[0].id,'device');assert.equal(nested.nodes[1].parentId,'device');
  assert.ok(nested.nodes[0].height>nested.nodes[1].height);
});
test('source freshness distinguishes missing files, changed files and analyzer drift',()=>{
  assert.match(freshnessText({files:[],status:'current',analyzerChanged:false}),/未变化/);
  assert.match(freshnessText({files:[{path:'old.py',status:'deleted'},{path:'a.py',status:'modified'}],analyzerChanged:true}),/old.py · 已删除/);
  assert.match(freshnessText({files:[],analyzerChanged:true}),/分析器/);
});
