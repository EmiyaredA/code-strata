import test from 'node:test';
import assert from 'node:assert/strict';
import { sourceGroups, namePrefixes, sameEvidence, locationLabel } from '../src/source-tags.js';
import { sequenceProjection, umlProjection, elementEvidence, normalizeTagMode, nodeSize } from '../src/uml-model.js';
import { keepStandardVisible } from '../src/standard-viewport.js';

test('standard selection stays visible after opening the source sheet or resizing chat',()=>{
  const v=keepStandardVisible({x:149,y:-453,zoom:1},{width:636,height:258},{width:338,height:259},{x:110,y:90});
  assert.ok(v.y+90>=20&&v.y+90<=238);assert.equal(v.zoom,1);
  const empty=keepStandardVisible({x:-1000,y:-1000,zoom:1},{width:636,height:258},{width:338,height:259});
  assert.ok(empty.x+338>0);assert.ok(empty.y+259>0);
});

const ref=(name,line,association='source',path='migration.py')=>({id:name+line,path,startLine:line,endLine:line,association,locationKind:association==='target-definition'?'definition':'source',symbol:{id:name,name,kind:'function'}});
test('collapsed names preserve real prefixes and grow to distinguish collisions',()=>{
  assert.deepEqual(namePrefixes(['migration.py','publish()']),['mig…','pub…']);
  const names=['parse_args()','parse_body()','publish()','中文函数()'];
  const short=namePrefixes(names);assert.equal(new Set(short).size,names.length);
  for(let i=0;i<names.length;i++)assert.ok(names[i].startsWith(short[i].replace(/…$/,'')));
  assert.equal(short[0],'parse_a…');assert.equal(short[1],'parse_b…');
});
test('file groups own functions, preserve callsite versus definition, and do not guess names',()=>{
  const refs=[ref('convert_legacy',79,'callsite'),ref('publish',31,'target-definition'),ref('convert_legacy',80,'callsite'),{path:'config.toml',startLine:1}];
  const groups=sourceGroups(refs);assert.equal(groups.length,2);
  assert.deepEqual(groups[0].functions.map(f=>f.name),['convert_legacy()','publish()']);
  assert.equal(groups[1].functions.length,0);
  assert.equal(locationLabel(groups[0].functions[0].ref),'调用处');
  assert.equal(locationLabel(groups[0].functions[1].ref),'被调用函数定义');
  assert.deepEqual(refs[0],ref('convert_legacy',79,'callsite'));
});
test('same-basename files stay separate and a precise clicked reference is identifiable',()=>{
  const a=ref('publish',31,'target-definition','a/migration.py'),b=ref('publish',31,'target-definition','b/migration.py');
  const groups=sourceGroups([a,b]);assert.notEqual(groups[0].prefix,groups[1].prefix);
  assert.equal(sameEvidence(a,b),false);assert.equal(sameEvidence(a,{...a}),true);
  assert.equal(sameEvidence(a,{...a,association:'definition'}),false);
});
test('relationship own evidence takes priority and endpoint references are marked supplemental',()=>{
  const own=ref('publish',79,'callsite'),endpoint=ref('publish',31,'target-definition');
  const edge={source:'a',target:'b',evidence:[own]};
  const refs=elementEvidence({nodes:[{id:'a',evidence:[own,endpoint]},{id:'b',evidence:[]}]},edge);
  assert.equal(refs.length,2);assert.equal(refs[0].origin,'element');assert.equal(refs[1].origin,'endpoint');
});
test('full tags enlarge geometry and move all sequence ports below the common header',()=>{
  const model={type:'sequence',nodes:[{id:'a',role:'participant',evidence:[ref('convert_legacy',79),ref('publish',31,'target-definition')]},{id:'b',role:'participant'}],edges:[{id:'ab',source:'a',target:'b',order:0}]};
  const small=sequenceProjection(model),large=sequenceProjection(model,'full');
  assert.ok(large.nodes[0].data.headerHeight>small.nodes[0].data.headerHeight);
  assert.equal(large.nodes[0].data.headerHeight,large.nodes[1].data.headerHeight);
  assert.deepEqual(large.edges,small.edges);assert.equal(large.nodes[0].data.messages[0].id,'ab');
});
test('ELK and wrapped routes preserve semantic endpoints across tag modes',async()=>{
  const model={type:'activity',nodes:[{id:'a',role:'action',evidence:[ref('publish',31)]},{id:'b',role:'action',evidence:[ref('convert_legacy',79)]}],edges:[{id:'ab',source:'a',target:'b',role:'flow'}]};
  const a=await umlProjection(model),b=await umlProjection(model,'full');
  assert.ok(b.nodes[0].height>a.nodes[0].height);assert.deepEqual(a.edges.map(({route,...edge})=>edge),b.edges.map(({route,...edge})=>edge));assert.notDeepEqual(a.edges[0].route,b.edges[0].route);
});

test('project source display preferences migrate to simple and full without changing evidence',()=>{
  for(const value of [undefined,null,'','folded','simple','unknown'])assert.equal(normalizeTagMode(value),'simple');
  for(const value of ['expanded','full'])assert.equal(normalizeTagMode(value),'full');
  const n={role:'component',label:'业务步骤',members:['save()'],evidence:[ref('publish',31)]};
  assert.deepEqual(nodeSize(n,'component','simple'),nodeSize({...n,evidence:[]},'component','simple'));
  assert.ok(nodeSize(n,'component','full').height>nodeSize(n,'component','simple').height);
  assert.equal(n.evidence[0].symbol.name,'publish');
  const choice={...n,role:'choice'};assert.deepEqual(nodeSize(choice,'state','simple'),nodeSize({...choice,evidence:[]},'state','simple'));
});
