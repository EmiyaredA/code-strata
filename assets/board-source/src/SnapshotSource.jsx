import React,{forwardRef,useEffect,useImperativeHandle,useLayoutEffect,useMemo,useRef,useState} from 'react';
import {LoaderCircle} from 'lucide-react';
import {SyntaxText} from './SyntaxCode.jsx';
import {highlightedLines} from './syntax.js';
import {SnapshotChunks,SOURCE_ROW,SOURCE_PAD,chunkStart,visibleSource,sourceWindow,referenceRanges,referenceClass} from './snapshot-source.js';

function tokensFor(entry) {
  if(!entry.tokens)entry.tokens=entry.file.content.length>200000?entry.lines.map(text=>[{text,className:''}]):highlightedLines(entry.file.content,entry.file.language,entry.file.path);
  return entry.tokens;
}
export const SnapshotSource=forwardRef(function SnapshotSource({source,readPage,onStatus},ref){
  const host=useRef(null),callbacks=useRef({readPage,onStatus}),initial=useRef(null),width=useRef(0);
  callbacks.current={readPage,onStatus};
  const [revision,redraw]=useState(0),[viewport,setViewport]=useState({top:0,height:230});
  const [reader]=useState(()=>new SnapshotChunks((start,end,signal)=>callbacks.current.readPage(start,end,signal),()=>redraw(v=>v+1)));
  const active=source.refs[source.index||0],target=source.focusLine||active?.startLine||1,info=reader.info;
  const range=visibleSource(viewport.top,viewport.height,info?.totalLines||1);
  const ranges=useMemo(()=>referenceRanges(source.refs,source.path,info?.totalLines),[source.refs,source.path,info?.totalLines]);
  const position=()=>{if(!host.current)return;const next={top:host.current.scrollTop,height:host.current.clientHeight};setViewport(old=>old.top===next.top&&old.height===next.height?old:next);};
  function jump(line){if(!host.current||!reader.info)return;const clamped=Math.min(reader.info.totalLines,Math.max(1,line));host.current.scrollTop=Math.max(0,(clamped-1)*SOURCE_ROW+SOURCE_PAD-host.current.clientHeight/3);position();}
  useImperativeHandle(ref,()=>({jump}),[reader.info]);
  useEffect(()=>{reader.disposed=false;reader.window([chunkStart(target)]);return()=>reader.dispose();},[reader]);
  useLayoutEffect(()=>{if(!info||initial.current===source.focusSerial)return;initial.current=source.focusSerial;jump(target);},[info?.totalLines,source.focusSerial]);
  useEffect(()=>{if(!info||initial.current===null)return;reader.window(sourceWindow(range,info.totalLines));},[reader,info?.totalLines,range.renderStart,range.renderEnd]);
  useLayoutEffect(()=>{if(!host.current)return;const observer=new ResizeObserver(position);observer.observe(host.current);position();return()=>observer.disconnect();},[]);
  useLayoutEffect(()=>{if(host.current&&host.current.scrollWidth>width.current)width.current=host.current.scrollWidth;},[revision,range.renderStart,range.renderEnd]);
  useEffect(()=>{callbacks.current.onStatus?.(info?{start:range.start,end:range.end,total:info.totalLines}:{start:0,end:0,total:0});},[info?.totalLines,range.start,range.end]);
  const first=reader.entries.get(chunkStart(target)),rows=[];
  if(info)for(let line=range.renderStart;line<=range.renderEnd;line++){
    const start=chunkStart(line),entry=reader.entries.get(start),ready=entry?.status==='ready';
    const text=ready?entry.lines[line-start]:null,tokens=ready?tokensFor(entry)[line-start]:null;
    const message=line===Math.max(start,range.start);
    const related=referenceClass(line,ranges,active,source.path);
    rows.push(<div key={line} data-line={line} className={`source-line ${related} ${ready?'':'is-placeholder'}`} style={{top:SOURCE_PAD+(line-1)*SOURCE_ROW}} aria-label={`第 ${line} 行${related==='is-target'?' · 当前引用':related?' · 关联依据':''}`}>
      <span className="line-number" title={related==='is-target'?'当前引用':related?'当前对象的其他依据':undefined}>{line}</span>
      {ready?<code><SyntaxText tokens={tokens}/>{!text&&' '}</code>:message&&entry?.status==='error'?<span className="source-chunk-error" role="alert"><span title={entry.error}>此段读取失败：{entry.error}</span><button className="text-button" onClick={()=>reader.request(start,true).catch(()=>{})}>重试此段</button></span>:<code>{message?'正在加载此段源码…':' '}</code>}
    </div>);
  }
  return <div className="uml-source-column uml-full-source" ref={host} tabIndex={0} aria-label="完整快照源码" onScroll={position}
    onKeyDown={e=>{if(e.target!==e.currentTarget)return;const el=host.current;let next;if(e.key==='Home')next=0;else if(e.key==='End')next=el.scrollHeight;else if(e.key==='PageDown')next=el.scrollTop+el.clientHeight-SOURCE_ROW;else if(e.key==='PageUp')next=el.scrollTop-el.clientHeight+SOURCE_ROW;else if(e.key==='ArrowDown')next=el.scrollTop+SOURCE_ROW;else if(e.key==='ArrowUp')next=el.scrollTop-SOURCE_ROW;if(next!==undefined){e.preventDefault();el.scrollTop=next;position();}}}>
    {!info?(first?.status==='error'?<p className="uml-error" role="alert">{first.error}<button className="text-button" onClick={()=>reader.request(chunkStart(target),true).catch(()=>{})}>重试读取</button></p>:<p className="uml-loading" role="status"><LoaderCircle size={15} className="spin"/>读取源码快照…</p>):<div className="uml-code-lines uml-virtual-code" style={{height:info.totalLines*SOURCE_ROW+SOURCE_PAD*2,minWidth:width.current||'100%'}}>{rows}</div>}
  </div>;
});
