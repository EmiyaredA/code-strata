import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { umlProjection, readableViewport, routedPath, edgeText } from '../src/uml-model.js';
const fixture=JSON.parse(await readFile(new URL('./fixtures/dense-component.json',import.meta.url)));
const measured=JSON.parse(await readFile(new URL('./fixtures/dense-component-measurements.json',import.meta.url)));
const intersects=(a,b)=>a.x<b.x+b.width-.1&&a.x+a.width>b.x+.1&&a.y<b.y+b.height-.1&&a.y+a.height>b.y+.1;
function absoluteNodes(nodes){const byId=new Map(nodes.map(n=>[n.id,n]));return nodes.map(n=>{let {x,y}=n.position,parent=n.parentId;while(parent){const p=byId.get(parent);x+=p.position.x;y+=p.position.y;parent=p.parentId;}return {...n,x,y};});}
test('dense compound layout reserves measured text and routes labels away from nodes and each other',async()=>{
  const sizes={nodes:new Map(measured.nodes),labels:new Map(measured.labels)};
  const p=await umlProjection(fixture,'folded',sizes),nodes=absoluteNodes(p.nodes),leaves=nodes.filter(n=>!n.data.container);
  for(const n of leaves)assert.ok(n.height>=sizes.nodes.get(n.id).height,`${n.id} reserves its wrapped content`);
  const labels=p.edges.map(e=>e.route.label).filter(Boolean);
  assert.equal(labels.length,fixture.edges.filter(e=>edgeText(e)).length);
  for(const label of labels){for(const n of leaves)assert.equal(intersects(label,n),false,`${label.text} overlaps ${n.id}`);}
  for(let i=0;i<labels.length;i++)for(let j=i+1;j<labels.length;j++)assert.equal(intersects(labels[i],labels[j]),false,`${labels[i].text} overlaps ${labels[j].text}`);
  const byId=new Map(nodes.map(n=>[n.id,n]));
  for(const edge of p.edges){assert.ok(edge.route.sections.length);for(const points of edge.route.sections)for(let i=1;i<points.length;i++)assert.ok(Math.abs(points[i-1].x-points[i].x)<1||Math.abs(points[i-1].y-points[i].y)<1,'ELK orthogonal route survives');
    const first=edge.route.sections[0][0],source=byId.get(edge.source);assert.ok(first.x>=source.x-.1&&first.x<=source.x+source.width+.1&&first.y>=source.y-.1&&first.y<=source.y+source.height+.1,'route starts at the actual source, including parent offsets');}
  assert.deepEqual(p.edges.map(({id,source,target})=>({id,source,target})),fixture.edges.map(({id,source,target})=>({id,source,target})));
});
test('labelled activity chains retain ELK label reservations instead of the unlabelled snake route',async()=>{
  const model={type:'activity',nodes:Array.from({length:4},(_,i)=>({id:String(i),role:'action',label:'action'})),edges:Array.from({length:3},(_,i)=>({id:'e'+i,source:String(i),target:String(i+1),label:'A long condition that needs its own reserved space'}))};
  const p=await umlProjection(model);assert.ok(p.edges.every(e=>e.route.label));assert.match(routedPath(p.edges[0].route.sections),/^M/);
});
test('restored camera recovers from empty space after a nested graph reflows',()=>{
  const nodes=[{id:'p',position:{x:1200,y:900},width:500,height:500,data:{container:true}},{id:'leaf',parentId:'p',position:{x:30,y:140},width:220,height:260,data:{}}];
  const old={x:20,y:20,zoom:.8},frame={width:600,height:500},next=readableViewport(nodes,old,frame);
  assert.notDeepEqual(next,old);assert.equal(next.zoom,old.zoom);
  const center={x:(1230+110)*next.zoom+next.x,y:(1040+130)*next.zoom+next.y};assert.ok(center.x>0&&center.x<600&&center.y>0&&center.y<500);
  assert.equal(readableViewport(nodes,next,frame),next);
});
