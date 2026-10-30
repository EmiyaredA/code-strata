import test from 'node:test';
import assert from 'node:assert/strict';
import {SnapshotChunks,chunkStart,visibleSource,sourceWindow,referenceRanges,referenceClass,referenceStops,citationEvidence,sourceIdentity} from '../src/snapshot-source.js';
const page=(start,end,total=994,path='main.ts',snapshotId='snapshot')=>({path,snapshotId,language:'typescript',startLine:start,endLine:Math.min(end,total),totalLines:total,content:Array.from({length:Math.min(end,total)-start+1},(_,i)=>`line ${start+i}`).join('\n')});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
test('994-line file spans exact non-overlapping 300-line chunks with bounded virtual rows',async()=>{
  const calls=[],cache=new SnapshotChunks(async(start,end)=>{calls.push([start,end]);return page(start,end);});
  for(const line of [656,1,994,300,301])await cache.request(line);
  assert.deepEqual(calls,[[601,900],[1,300],[901,1200],[301,600]]);
  assert.deepEqual([...cache.entries.values()].sort((a,b)=>a.start-b.start).flatMap(e=>e.lines),Array.from({length:994},(_,i)=>`line ${i+1}`));
  for(const position of [0,655*23,993*23]){const r=visibleSource(position,400,994);assert.ok(r.renderEnd-r.renderStart<45);assert.ok(r.start>=1&&r.end<=994);}
  assert.equal(chunkStart(300),1);assert.equal(chunkStart(301),301);assert.equal(visibleSource(994*23,400,994).end,994);
  const huge=visibleSource(50000*23,600,100000);assert.ok(huge.renderEnd-huge.renderStart<55);assert.ok(sourceWindow(huge,100000).length<=4);cache.dispose();
});
test('only current-object ranges highlight, overlaps merge and navigation-only locations are not evidence',()=>{
  const refs=[{path:'main.ts',startLine:656,endLine:992},{path:'main.ts',startLine:500,endLine:600},{path:'main.ts',startLine:710,endLine:750},{path:'other.py',startLine:1,endLine:40},{path:'main.ts',startLine:1,endLine:994,navigationOnly:true}];
  const ranges=referenceRanges(refs,'main.ts',994);assert.deepEqual(ranges,[{start:500,end:600},{start:656,end:992}]);
  assert.equal(referenceClass(1,ranges,refs[0],'main.ts'),'');assert.equal(referenceClass(656,ranges,refs[0],'main.ts'),'is-target');assert.equal(referenceClass(550,ranges,refs[0],'main.ts'),'is-related');assert.equal(referenceClass(994,ranges,refs[0],'main.ts'),'');
  assert.deepEqual(referenceStops([...refs,refs[0]],'main.ts').map(r=>r.index),[1,0,2]);assert.equal(citationEvidence(refs,'main.ts',720),2);assert.equal(citationEvidence(refs,'main.ts',100),-1);
  assert.deepEqual(referenceRanges([{path:'main.ts',startLine:1,endLine:1,navigationOnly:true}],'main.ts'),[]);
});
test('cache caps entries at twelve and reuses a ready block without reading again',async()=>{
  let reads=0;const cache=new SnapshotChunks(async(s,e)=>{reads++;return page(s,e,10000);});
  for(let i=0;i<18;i++){await cache.request(i*300+1);await tick();assert.ok(cache.entries.size<=12);}
  const before=reads;await cache.request(5101);assert.equal(reads,before);assert.equal(cache.entries.has(1),false);cache.dispose();
});
test('failed chunk preserves loaded content and retry only rereads that chunk',async()=>{
  let fail=true;const calls=[],cache=new SnapshotChunks(async(s,e)=>{calls.push(s);if(s===301&&fail)throw new Error('offline');return page(s,e);});
  await cache.request(1);await assert.rejects(cache.request(301),/offline/);await tick();assert.equal(cache.entries.get(1).lines[0],'line 1');assert.equal(cache.entries.get(301).status,'error');
  await assert.rejects(cache.request(301),/offline/);assert.deepEqual(calls,[1,301]);fail=false;await cache.request(301,true);assert.deepEqual(calls,[1,301,301]);assert.equal(cache.entries.get(301).lines[0],'line 301');cache.dispose();
});
test('late reads after window cancellation or close cannot populate a new file or exceed concurrency',async()=>{
  const pending=[],cache=new SnapshotChunks((s,e,signal)=>new Promise(resolve=>pending.push({s,e,signal,resolve})));
  cache.window([1,301,601]);await tick();assert.equal(pending.length,2);assert.equal(cache.active,2);
  cache.window([901]);assert.equal(pending[0].signal.aborted,true);assert.equal(pending[1].signal.aborted,true);
  pending[0].resolve(page(1,300));pending[1].resolve(page(301,600));await tick();assert.equal(cache.entries.has(1),false);assert.equal(pending.length,3);
  cache.dispose();pending[2].resolve(page(901,1200));await tick();assert.equal(cache.entries.size,0);assert.equal(cache.info,null);
  assert.notEqual(sourceIdentity({project:'a',snapshotId:'one',path:'a.py'}),sourceIdentity({project:'a',snapshotId:'two',path:'a.py'}));
});
test('a block with wrong range or file identity is rejected and cannot replace historical text',async()=>{
  const cache=new SnapshotChunks(async(s,e)=>page(s,e,994,s===1?'main.ts':'wrong.ts'));
  await cache.request(1);await assert.rejects(cache.request(301),/身份不匹配/);assert.equal(cache.info.path,'main.ts');assert.equal(cache.entries.get(1).lines[0],'line 1');cache.dispose();
  const broken=new SnapshotChunks(async(s,e)=>({...page(s,e),startLine:s+1}));await assert.rejects(broken.request(1),/范围不匹配/);broken.dispose();
});
test('initial failure keeps metadata unavailable until an explicit successful retry',async()=>{
  let failed=true;const cache=new SnapshotChunks(async(s,e)=>{if(failed)throw new Error('历史正文暂不可读');return page(s,e);});
  await assert.rejects(cache.request(656),/历史正文/);assert.equal(cache.info,null);assert.equal(cache.entries.get(601).status,'error');failed=false;
  await cache.request(656,true);assert.equal(cache.info.totalLines,994);assert.equal(cache.entries.get(601).lines[55],'line 656');cache.dispose();
});
test('same-file symbol enrichment and selection changes keep the reader identity, project and version changes do not',()=>{
  const source={project:'project',snapshotId:'saved',diagramId:'d',revision:1,path:'main.ts',index:0,refs:[]};
  assert.equal(sourceIdentity(source),sourceIdentity({...source,index:2,focusSerial:15,refs:[{symbol:{name:'new metadata'}}]}));
  for(const patch of [{project:'other'},{snapshotId:'new'},{revision:2},{path:'other.ts'},{diagramId:'different'}])assert.notEqual(sourceIdentity(source),sourceIdentity({...source,...patch}));
});
