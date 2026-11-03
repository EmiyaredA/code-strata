import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {TYPE_OPTIONS,TYPE_GROUPS} from '../src/notation.js';
import {umlProjection,elementEvidence,normalizeTagMode} from '../src/uml-model.js';
import {localStandardSvg} from '../src/standard-svg.js';
const models=JSON.parse(await readFile(new URL('./fixtures/notation-gallery.json',import.meta.url)));
const overlap=(a,b)=>a.x<b.x+b.width-.1&&a.x+a.width>b.x+.1&&a.y<b.y+b.height-.1&&a.y+a.height>b.y+.1;
function boxes(p){const by=new Map(p.nodes.map(n=>[n.id,n]));return p.nodes.map(n=>{let x=n.position.x,y=n.position.y,parent=n.parentId;while(parent){const a=by.get(parent);x+=a.position.x;y+=a.position.y;parent=a.parentId;}return {...n,x,y};});}
test('grouped selector exposes 14 UML and two process notations without selectable headings',()=>{
 assert.equal(TYPE_OPTIONS.length,16);assert.equal(TYPE_GROUPS.length,4);assert.equal(new Set(TYPE_OPTIONS.map(x=>x.value)).size,16);assert.ok(TYPE_OPTIONS.every(x=>x.group&&x.label));
});
for(const m of models)test(`${m.type}: both modes retain semantic IDs, source evidence and deterministic standard SVG`,async()=>{
 for(const mode of ['simple','full']){const p=await umlProjection(m,mode);assert.equal(p.nodes.length,m.nodes.length);assert.equal(p.edges.length,m.edges.length);assert.deepEqual(p.edges.map(e=>[e.id,e.source,e.target]),m.edges.map(e=>[e.id,e.source,e.target]));for(const n of p.nodes)assert.ok(Number.isFinite(n.position.x)&&Number.isFinite(n.position.y));}
 const svg=await localStandardSvg(m);assert.equal(svg,await localStandardSvg(m));for(const el of [...m.nodes,...m.edges]){assert.ok(svg.includes(`data-element="${el.id}"`));assert.ok(elementEvidence(m,el).length);}
 assert.ok(!svg.includes('source-function-tag'));assert.ok(!svg.includes('foreignObject'));assert.ok(svg.includes('tabindex="0"'));
});
test('swimlanes have uniform bounds, correct membership and collision-free cross-lane edge labels',async()=>{
 const m=models.find(m=>m.type==='swimlane'),p=await umlProjection(m),lanes=p.nodes.filter(n=>n.data.container),leaves=boxes(p).filter(n=>!n.data.container);
 assert.equal(new Set(lanes.map(n=>n.height)).size,1);assert.ok(lanes[0].position.x<lanes[1].position.x);
 for(const n of p.nodes.filter(n=>!n.data.container)){assert.ok(n.parentId);assert.ok(n.position.y>lanes[0].data.headerHeight);}
 const labels=p.edges.map(e=>e.route.label).filter(Boolean);for(const l of labels)for(const n of leaves)assert.equal(overlap(l,n),false);
 for(let i=0;i<labels.length;i++)for(let j=i+1;j<labels.length;j++)assert.equal(overlap(labels[i],labels[j]),false);
});
test('logical timing uses ordered intervals in each signal rather than a dependency graph',async()=>{
 const m=models.find(m=>m.type==='timing'),p=await umlProjection(m),events=p.nodes.filter(n=>n.data.node.role==='state-event').sort((a,b)=>a.data.node.order-b.data.node.order);
 assert.ok(events[0].position.x<events[1].position.x&&events[1].position.x<events[2].position.x);assert.equal(new Set(events.map(n=>n.position.y)).size,1);assert.match(await localStandardSvg(m),/非运行耗时/);
});
test('communication numbers and composite ports survive standard projection',async()=>{
 const c=models.find(m=>m.type==='communication');assert.match(await localStandardSvg(c),/0:|1:/);
 const p=await umlProjection(models.find(m=>m.type==='composite')),port=p.nodes.find(n=>n.data.node.role==='port'&&n.data.node.side==='left');assert.ok(port.position.x<0);
});
test('SVG text cannot insert markup or active content',async()=>{
 const m=structuredClone(models.find(m=>m.type==='flowchart'));m.nodes[0].label='<script>alert(1)</script>';const svg=await localStandardSvg(m);assert.ok(!svg.includes('<script>'));assert.ok(svg.includes('&lt;script&gt;'));
});
test('swimlane loops and parallel branches preserve original edges and avoid node intersections',async()=>{
 const nodes=[{id:'l',role:'lane',label:'编排',order:0},{id:'r',role:'lane',label:'存储',order:1},...['s','d','a','f','b','c','j','e'].map((id,i)=>({id,label:id,role:{s:'start',d:'decision',f:'fork',j:'join',e:'end'}[id]||'action',parentId:i%2?'r':'l'}))];
 const pairs=[['s','d'],['d','a'],['a','d'],['d','f'],['f','b'],['f','c'],['b','j'],['c','j'],['j','e']];
 const edges=pairs.map(([source,target],i)=>({id:'e'+i,source,target,role:'flow',label:'条件 '+i})),m={type:'swimlane',nodes,edges};
 const p=await umlProjection(m);assert.deepEqual(p.edges.map(e=>[e.source,e.target]),pairs);const leaves=boxes(p).filter(n=>!n.data.container);
 for(let i=0;i<leaves.length;i++)for(let j=i+1;j<leaves.length;j++)assert.equal(overlap(leaves[i],leaves[j]),false);
 assert.ok(p.edges.every(e=>e.route.sections[0].length>=2));
});
test('local SVG edge paths keep mouse selection but labelled evidence owns keyboard focus',async()=>{
 const svg=await localStandardSvg(models.find(m=>m.type==='flowchart'));assert.match(svg,/tabindex="-1" role="presentation"/);assert.match(svg,/tabindex="0" role="button"/);
});
