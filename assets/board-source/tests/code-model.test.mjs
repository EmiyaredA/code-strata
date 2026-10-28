import {test} from 'node:test';
import assert from 'node:assert/strict';
import {containsRange,innermost,frameKey} from '../src/code-model.js';
test('UTF16 end-exclusive ranges distinguish same-line and multiline nesting',()=>{
  const outer={start:[2,0],end:[4,8]},inner={start:[3,14],end:[3,17]};
  assert.ok(containsRange(outer,inner));assert.ok(!containsRange(inner,outer));
  const nodes=[{id:'outer',range:outer},{id:'inner',range:inner}];assert.equal(innermost(nodes,inner).id,'inner');
});
test('navigation keys distinguish levels, groups, and scope; zoom is not semantic navigation',()=>{
  assert.notEqual(frameKey({view:'functions',focusId:'f'}),frameKey({view:'logic',focusId:'f'}));
  assert.notEqual(frameKey({view:'files',groupId:'a'}),frameKey({view:'files',groupId:'b'}));
  assert.equal(frameKey({view:'logic',focusId:'f',viewport:{zoom:1}}),frameKey({view:'logic',focusId:'f',viewport:{zoom:.5}}));
 assert.notEqual(frameKey({view:'functions',focusId:'file',moduleTopLevel:true}),frameKey({view:'functions',focusId:'file'}));
});
import {focusLayout,rankedLayout} from '../src/relation-layout.js';
test('focused calls have explicit upstream, current and downstream columns; containment is not a call',()=>{
 const objects=['caller','focus','callee','nested'].map(id=>({id,name:id,kind:'function'}));
 const result=focusLayout(objects,[{id:'a',kind:'calls',source:'caller',target:'focus'},{id:'b',kind:'calls',source:'focus',target:'callee'},{id:'c',kind:'contains',source:'focus',target:'nested'}],'focus');
 const center=result.nodes.find(n=>n.object.id==='focus'),left=result.nodes.find(n=>n.object.id==='caller'),right=result.nodes.find(n=>n.object.id==='callee');
 assert.ok(left.x<center.x&&center.x<right.x);assert.ok(!result.nodes.some(n=>n.object.id==='nested'));
 assert.equal(result.edges.length,2);
});
test('mutual calls duplicate a visual position, preserve canonical object identity and distinguish recursion',()=>{
 const objects=['a','b'].map(id=>({id,name:id,kind:'function'}));
 const result=focusLayout(objects,[{id:'ab',kind:'calls',source:'a',target:'b'},{id:'ba',kind:'calls',source:'b',target:'a'},{id:'aa',kind:'calls',source:'a',target:'a'}],'a');
 assert.equal(result.nodes.filter(n=>n.object.id==='b').length,2);
 assert.ok(result.edges.some(r=>r.source===r.target&&r.cycle));
 assert.ok(result.nodes.filter(n=>n.object.id==='b').every(n=>n.mutual));
});
test('unknown calls collapse without inventing an internal target',()=>{
 const nodes=[{id:'f',kind:'function',name:'f'},{id:'call',kind:'call',name:'handler',status:'unresolved'}],edges=[{id:'u',kind:'unresolved-call',source:'f',target:'call'}];
 const collapsed=focusLayout(nodes,edges,'f'),expanded=focusLayout(nodes,edges,'f',{showUnknown:true});
 assert.ok(collapsed.nodes.some(n=>n.object.kind==='summary'));assert.ok(!collapsed.nodes.some(n=>n.object.id==='call'));
 assert.ok(expanded.nodes.some(n=>n.object.id==='call'));
});
test('overview ranks dependency edges by direction, marks cycles, and separates isolated nodes',()=>{
 const nodes=['a','b','c','isolated'].map(id=>({id,name:id}));
 const result=rankedLayout(nodes,[{id:'ab',source:'a',target:'b'},{id:'bc',source:'b',target:'c'},{id:'cb',source:'c',target:'b'}]);
 const a=result.nodes.find(n=>n.id==='a'),b=result.nodes.find(n=>n.id==='b'),c=result.nodes.find(n=>n.id==='c');
 assert.ok(a.x<b.x);assert.equal(b.x,c.x);assert.ok(b.cyclic&&c.cyclic);assert.equal(result.isolatedCount,1);assert.ok(!result.nodes.some(n=>n.id==='isolated'));
});

test("fit viewport keeps known cards below the guide and inside the canvas", async () => {
  const {layoutViewport} = await import('../src/relation-layout.js');
  const cards = [{x:-80,y:0,width:280,height:92},{x:260,y:800,width:280,height:92}];
  const view = layoutViewport({nodes:cards},900,540);
  for (const card of cards) {
    assert.ok(card.x*view.zoom+view.x>=0 && (card.x+card.width)*view.zoom+view.x<=900);
    assert.ok(card.y*view.zoom+view.y>=42 && (card.y+card.height)*view.zoom+view.y<=540);
  }
});

test('opening the chat or hierarchy drawer keeps the same graph center and user zoom', async () => {
  const {resizeViewport} = await import('../src/relation-layout.js');
  const before = {width:1100,height:800}, after = {width:580,height:800}, viewport = {x:430,y:78,zoom:.9};
  const next = resizeViewport(viewport,before,after);
  assert.equal(next.zoom,viewport.zoom);
  assert.equal((before.width/2-viewport.x)/viewport.zoom,(after.width/2-next.x)/next.zoom);
  assert.equal(next.y,viewport.y);
  assert.deepEqual(resizeViewport(next,after,before),viewport);
  const cards = [{x:0,y:72,width:240,height:104},{x:0,y:224,width:240,height:104},{x:0,y:376,width:240,height:104}];
  const shorter = resizeViewport({x:200,y:-8,zoom:1},{width:700,height:800},{width:500,height:570},cards);
  for (const card of cards) { assert.ok(card.y+shorter.y>=52); assert.ok(card.y+card.height+shorter.y<=546); }
});
