export const SOURCE_CHUNK = 300;
export const SOURCE_ROW = 23;
export const SOURCE_PAD = 8;
export const chunkStart = line => Math.floor((Math.max(1,line)-1)/SOURCE_CHUNK)*SOURCE_CHUNK+1;
export const sourceIdentity = source => JSON.stringify([source.project,source.snapshotId,source.diagramId,source.revision,source.conversationId,source.path]);
export function visibleSource(scrollTop,height,total) {
  const start=Math.max(1,Math.min(total,Math.floor(Math.max(0,scrollTop-SOURCE_PAD)/SOURCE_ROW)+1));
  const end=Math.max(start,Math.min(total,Math.ceil(Math.max(0,scrollTop+height-SOURCE_PAD)/SOURCE_ROW)));
  return {start,end,renderStart:Math.max(1,start-12),renderEnd:Math.min(total,end+12)};
}
export function sourceWindow(range,total) {
  const first=chunkStart(range.renderStart),last=chunkStart(range.renderEnd),blocks=[];
  for(let start=first;start<=last;start+=SOURCE_CHUNK)blocks.push(start);
  if(first>SOURCE_CHUNK)blocks.push(first-SOURCE_CHUNK);
  if(last+SOURCE_CHUNK<=total)blocks.push(last+SOURCE_CHUNK);
  return blocks;
}
export function referenceRanges(refs,path,total=Infinity) {
  const ranges=refs.filter(r=>r.path===path&&!r.navigationOnly&&Number.isInteger(r.startLine)&&r.startLine>0&&r.endLine>=r.startLine)
    .map(r=>({start:r.startLine,end:Math.min(total,r.endLine)})).filter(r=>r.start<=r.end).sort((a,b)=>a.start-b.start||a.end-b.end);
  const merged=[];
  for(const range of ranges){const last=merged.at(-1);if(last&&range.start<=last.end+1)last.end=Math.max(last.end,range.end);else merged.push({...range});}
  return merged;
}
export function referenceClass(line,ranges,active,path) {
  if(active?.path===path&&!active.navigationOnly&&line>=active.startLine&&line<=active.endLine)return 'is-target';
  return ranges.some(r=>line>=r.start&&line<=r.end)?'is-related':'';
}
export function referenceStops(refs,path) {
  const unique=new Map();refs.forEach((r,index)=>{if(r.path===path&&!r.navigationOnly){const key=`${r.startLine}:${r.endLine}`;if(!unique.has(key))unique.set(key,{index,start:r.startLine,end:r.endLine});}});
  return [...unique.values()].sort((a,b)=>a.start-b.start||a.end-b.end);
}
export function citationEvidence(refs,path,line) {
  return refs.map((r,index)=>({r,index})).filter(({r})=>r.path===path&&!r.navigationOnly&&r.startLine<=line&&r.endLine>=line)
    .sort((a,b)=>(a.r.endLine-a.r.startLine)-(b.r.endLine-b.r.startLine))[0]?.index??-1;
}
const abortError=()=>Object.assign(new Error('源码读取已取消'),{name:'AbortError'});

// One reader owns one immutable file. Window requests never replace the file or
// selection; late responses can only populate their own matching cache entry.
export class SnapshotChunks {
  constructor(read,onChange=()=>{},limit=12) {
    this.read=read;this.onChange=onChange;this.limit=limit;this.entries=new Map();this.wanted=new Set();this.active=0;this.queue=[];this.info=null;this.disposed=false;
  }
  window(starts) {
    if(this.disposed)return;
    this.wanted=new Set(starts.map(chunkStart).filter(start=>!this.info||start<=this.info.totalLines));
    for(const [start,entry] of this.entries)if(!this.wanted.has(start)&&['queued','loading'].includes(entry.status)){
      entry.controller.abort();entry.reject(abortError());this.entries.delete(start);
    }
    this.queue=this.queue.filter(e=>this.entries.get(e.start)===e);
    for(const start of this.wanted)this.request(start).catch(()=>{});
    this.prune();
  }
  request(line,retry=false) {
    if(this.disposed)return Promise.reject(abortError());
    const start=chunkStart(line),old=this.entries.get(start);
    if(old&&(!retry||old.status!=='error')){this.entries.delete(start);this.entries.set(start,old);return old.promise;}
    let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});
    // A canceled prefetch may have no consumer; its error is represented in state.
    promise.catch(()=>{});
    const entry={start,status:'queued',controller:new AbortController(),promise,resolve,reject};
    this.entries.set(start,entry);this.queue.push(entry);this.prune();this.pump();return promise;
  }
  pump() {
    while(!this.disposed&&this.active<2&&this.queue.length){const entry=this.queue.shift();if(this.entries.get(entry.start)!==entry)continue;
      this.active++;entry.status='loading';this.onChange();
      Promise.resolve().then(()=>this.read(entry.start,entry.start+SOURCE_CHUNK-1,entry.controller.signal)).then(file=>{
        if(this.disposed||entry.controller.signal.aborted||this.entries.get(entry.start)!==entry)throw abortError();
        if(file.startLine!==entry.start||file.endLine>entry.start+SOURCE_CHUNK-1||file.endLine<file.startLine||file.totalLines<file.endLine)throw new Error('源码分块范围不匹配');
        if(this.info&&(file.snapshotId!==this.info.snapshotId||file.path!==this.info.path||file.totalLines!==this.info.totalLines))throw new Error('源码快照身份不匹配');
        const lines=file.content.split('\n');if(lines.length!==file.endLine-file.startLine+1)throw new Error('源码分块行数不匹配');
        entry.status='ready';entry.file=file;entry.lines=lines;
        this.info={snapshotId:file.snapshotId,path:file.path,language:file.language,totalLines:file.totalLines};entry.resolve(file);
      }).catch(error=>{
        if(!this.disposed&&this.entries.get(entry.start)===entry){if(error.name==='AbortError')this.entries.delete(entry.start);else {entry.status='error';entry.error=error.message;}}
        entry.reject(error);
      }).finally(()=>{this.active--;this.prune();if(!this.disposed)this.onChange();this.pump();});
    }
  }
  prune(){for(const [start,entry] of this.entries){if(this.entries.size<=this.limit)break;if(!this.wanted.has(start)&&!['queued','loading'].includes(entry.status))this.entries.delete(start);}}
  dispose(){this.disposed=true;for(const entry of this.entries.values()){entry.controller.abort();if(['queued','loading'].includes(entry.status))entry.reject(abortError());}this.queue=[];this.entries.clear();this.info=null;}
}
