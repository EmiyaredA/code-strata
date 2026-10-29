import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { PanelLeftClose, PanelLeftOpen, Link2, X, List, History, RefreshCw, Info, LoaderCircle, GitBranch, MessageSquare, FileClock, ChevronDown } from 'lucide-react';
import { Tree } from './CodeTree.jsx';
import { parents } from './model.js';
import { SyntaxCode } from './SyntaxCode.jsx';
import { Markdown } from './ExplorationMarkdown.jsx';
import { ExplorationGraph } from './ExplorationGraph.jsx';
import { ReactFlowProvider } from '@xyflow/react';
import { UmlGraph } from './UmlGraph.jsx';
import { StandardUml } from './StandardUml.jsx';
import { SourceTags } from './SourceTags.jsx';
import { sameEvidence, locationLabel, mergeSourceFile } from './source-tags.js';
import { UML_TYPES, tabKey, restoreTabs, closeTab, elementEvidence, freshnessText, versionKey, requestGate } from './uml-model.js';
import { explorationApi as api } from './exploration-api.js';
import './uml-workspace.css';

function saved(project) {try{return JSON.parse(localStorage.getItem(tabKey(project))||'null');}catch{return null;}}
function SourceInspector({source, loading, error, height, setHeight, onClose, onEvidence, onPage, onQuestion, onCitation, check, sourceMap, retryMap,tagMode}) {
  const ref=useRef(null), drag=useRef(null);
  useEffect(()=>{ref.current?.querySelector('.is-target')?.scrollIntoView({block:'center'});},[source?.file?.path,source?.file?.startLine,source?.index]);
  useEffect(()=>{const key=e=>{if(e.key==='Escape'){e.preventDefault();e.stopImmediatePropagation();onClose();}};document.addEventListener('keydown',key,true);return()=>document.removeEventListener('keydown',key,true);},[onClose]);
  const file=source?.file, evidence=source?.refs?.[source.index||0];
  return <section ref={ref} className="uml-inspector" role="dialog" aria-modal="false" aria-label="源码依据与 AI 解释" style={{height}}>
    <div className="uml-sheet-resize" role="separator" aria-label="调整源码检查窗高度" aria-orientation="horizontal" aria-valuemin={180} aria-valuemax={650} aria-valuenow={Math.round(height)} tabIndex={0}
      onPointerDown={e=>{drag.current={y:e.clientY,height};e.currentTarget.setPointerCapture(e.pointerId);}}
      onPointerMove={e=>{if(drag.current)setHeight(Math.max(180,Math.min(650,drag.current.height+drag.current.y-e.clientY)));}}
      onPointerUp={()=>{drag.current=null;}} onPointerCancel={()=>{drag.current=null;}}
      onKeyDown={e=>{if(['ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();setHeight(Math.max(180,Math.min(650,height+(e.key==='ArrowUp'?24:-24))));}}}><span/></div>
    <header><div><strong>源码依据 · {source?.element?.label||file?.path?.split('/').at(-1)||'读取源码'}</strong><small title={file?.path}>{file?.path||evidence?.path} {evidence&&`· ${evidence.locationKind==='call'?'调用处':evidence.locationKind==='definition'?'定义':'源码'} L${evidence.startLine}–${evidence.endLine}`} <span>· 生成时快照</span></small></div><button className="icon-button" onClick={onClose} aria-label="关闭源码检查窗"><X size={17}/></button></header>
    <SourceTags refs={source.refs} mode={tagMode} onChoose={ref=>onEvidence(source.refs.findIndex(r=>sameEvidence(r,ref)))}/>
    {sourceMap?.status&&sourceMap.status!=='ready'&&<div className="uml-source-map-status" role="status">{sourceMap.status==='building'?'正在索引快照中的函数归属…':sourceMap.message}{sourceMap.status==='failed'&&<button className="text-button" onClick={retryMap}>重试函数索引</button>}</div>}
    {!!source?.refs?.length&&source.refs.length>1&&<div className="uml-evidence-tabs" aria-label="源码依据位置">{source.refs.map((r,i)=><button key={`${r.path}:${r.startLine}:${i}`} aria-pressed={i===source.index} onClick={()=>onEvidence(i)} title={r.path}>{r.origin==='endpoint'?'端点补充 · ':''}{locationLabel(r)} · {r.symbol?.name||r.path.split('/').at(-1)}:{r.startLine}</button>)}</div>}
    {check&&(check.status!=='current'||check.analyzerChanged)&&<div className="uml-source-warning"><FileClock size={13}/><span>代码已变化或无法验证，当前显示生成时源码。</span><small title={freshnessText(check)}>{freshnessText(check)}</small></div>}
    <div className="uml-inspector-columns"><div className="uml-source-column" tabIndex={0} aria-label="快照源码">
      {loading?<p className="uml-loading"><LoaderCircle size={15} className="spin"/>读取源码快照…</p>:error?<p role="alert" className="uml-error">{error}</p>:file&&<div className="uml-code-lines">{file.content.split('\n').map((line,i)=>{const number=file.startLine+i;return <div key={number} className={`source-line ${number>=(evidence?.startLine||0)&&number<=(evidence?.endLine||0)?'is-target':''}`}><span className="line-number">{number}</span><SyntaxCode text={line||' '} language={file.language} path={file.path}/></div>;})}</div>}
    </div><aside className="uml-ai-explanation"><strong><MessageSquare size={15}/>AI 解释</strong><Markdown text={source?.element?.explanation||'这处源码尚无单独的 AI 解释，可携带所选位置在会话中追问。'} onSource={onCitation}/>
      <small className="uml-inference-label">{source?.element?.basis==='analyzer'?'关系来自分析器；文字为 AI 解读':'依据源码整理 · 不代表实际运行轨迹'}</small>
      <button className="button uml-followup" onClick={()=>onQuestion(`请解释当前图中「${source?.element?.label||file?.path||'所选源码'}」的实现与作用，引用源码依据。`)}>继续追问</button></aside></div>
    {file&&<footer><span>快照 {source.snapshotId?.slice(0,8)} · 第 {file.startLine}–{file.endLine} 行 / {file.totalLines} 行</span><div><button className="text-button" disabled={file.startLine<=1||loading} onClick={()=>onPage(Math.max(1,file.startLine-250))}>上一段</button><button className="text-button" disabled={file.endLine>=file.totalLines||loading} onClick={()=>onPage(file.endLine+1)}>下一段</button></div></footer>}
  </section>;
}

export function UmlWorkspace({ data, drawer, renderChat, onRefresh, busy, sourceEntry }) {
  const project=data.project.root;
  const [catalog,setCatalog]=useState([]),[tabs,setTabs]=useState({tabs:[],active:null}),[diagram,setDiagram]=useState(null);
  const [version,setVersion]=useState(null),[versions,setVersions]=useState([]),[listOpen,setListOpen]=useState(false),[historyOpen,setHistoryOpen]=useState(false),[drafts,setDrafts]=useState([]);
  const [error,setError]=useState(''),[loading,setLoading]=useState(false),[checks,setChecks]=useState({});
  const [expanded,setExpanded]=useState(new Set()),[directoryOpen,setDirectoryOpen]=useState(()=>{try{return localStorage.getItem('strata:uml:directory')!=='false';}catch{return true;}}),[directoryWidth,setDirectoryWidth]=useState(240),[narrow,setNarrow]=useState(false);
  const [source,setSource]=useState(null),[sourceLoading,setSourceLoading]=useState(false),[sourceError,setSourceError]=useState(''),[sheetHeight,setSheetHeight]=useState(400),[selection,setSelection]=useState(null),[uiTick,setUiTick]=useState(0);
  const [tagMode,setTagMode]=useState('folded'),[viewMode,setViewMode]=useState('interactive'),[sourceMap,setSourceMap]=useState(null),[mapRetry,setMapRetry]=useState(0);
  const host=useRef(null),treeHost=useRef(null),resize=useRef(null),chatRequest=useRef(null),seen=useRef(null),ready=useRef(false),sourceSerial=useRef(requestGate()),loadSerial=useRef(requestGate()),sourceAbort=useRef(null),sourceReturnFocus=useRef(null),diagramRef=useRef(null),states=useRef({}),preferences=useRef(null),projectRef=useRef(project),tabsRef=useRef(tabs),interaction=useRef(0),runInteraction=useRef(0);
  projectRef.current=project;tabsRef.current=tabs;diagramRef.current=diagram;
  const model=useMemo(()=>{if(!diagram)return null;const original=diagram.model;if(!sourceMap||sourceMap.key!==versionKey(diagram)||sourceMap.status!=='ready')return original;
    const enrich=items=>items.map(e=>({...e,evidence:sourceMap.elements[e.id]||e.evidence}));
    const nodes=enrich(original.nodes),edges=enrich(original.edges);return {...original,nodes,edges,evidence:[...(original.evidence||[]),...nodes.flatMap(n=>n.evidence||[]),...edges.flatMap(e=>e.evidence||[])]};
  },[diagram,sourceMap]);
  diagramRef.current=diagram?{...diagram,model}:null;
  const key=diagram?versionKey(diagram):'', check=checks[key];
  const currentState=states.current[key]||{};

  useEffect(()=>{sourceSerial.current.invalidate();sourceAbort.current?.abort();loadSerial.current.invalidate();ready.current=false;seen.current=null;preferences.current=saved(project);states.current=preferences.current?.states||{};
    setTabs({tabs:[],active:null});setCatalog([]);setDiagram(null);setSource(null);setSourceLoading(false);setSelection(null);setChecks({});setVersion(null);setVersions([]);setError('');setExpanded(new Set());setListOpen(false);setHistoryOpen(false);
    setTagMode(preferences.current?.tagMode==='expanded'?'expanded':'folded');setViewMode(preferences.current?.viewMode==='standard'?'standard':'interactive');setSourceMap(null);
  },[project]);
  const refreshCatalog=useCallback(async()=>{
    if(!project)return [];
    let offset=0,all=[],page;
    do {page=await api(`/api/explore/diagrams?offset=${offset}`);all.push(...page.diagrams);offset=page.nextOffset;}while(offset!==null);
    if(projectRef.current!==project)return [];
    setCatalog(all);
    if(!ready.current){const restored=restoreTabs(preferences.current,all);if(!preferences.current&&all.length){restored.tabs=[all.at(-1).id];restored.active=all.at(-1).id;}setTabs(restored);ready.current=true;}
    else {const incoming=all.filter(d=>!seen.current?.has(d.id)).map(d=>d.id);if(incoming.length)setTabs(old=>({tabs:[...new Set([...old.tabs,...incoming])],active:old.active||incoming[0]}));}
    seen.current=new Set(all.map(d=>d.id));return all;
  },[project]);
  useEffect(()=>{if(!project)return;let disposed=false,timer;async function poll(){try{await refreshCatalog();}catch(e){if(!disposed&&projectRef.current===project)setError(e.message);}if(!disposed)timer=setTimeout(poll,4000);}poll();return()=>{disposed=true;clearTimeout(timer);};},[refreshCatalog]);
  useEffect(()=>{if(!ready.current)return;try{localStorage.setItem(tabKey(project),JSON.stringify({...tabs,states:states.current,tagMode,viewMode}));}catch{}},[tabs,project,uiTick,tagMode,viewMode]);
  useEffect(()=>{if(!diagram||diagram.model.type==='legacy')return;const controller=new AbortController();let timer;
    setSourceMap({key:versionKey(diagram),status:'building'});
    async function read(){try{const result=await api(`/api/explore/diagrams/${diagram.id}/source-map?revision=${diagram.revision}${mapRetry?'&retry=1':''}`,undefined,controller.signal);
      if(controller.signal.aborted)return;setSourceMap({...result,key:versionKey(diagram)});if(result.status==='building')timer=setTimeout(read,500);
    }catch(e){if(!controller.signal.aborted)setSourceMap({key:versionKey(diagram),status:'failed',message:e.message});}}
    read();return()=>{controller.abort();clearTimeout(timer);};
  },[diagram?.id,diagram?.revision,mapRetry]);
  useEffect(()=>{if(!model||sourceMap?.status!=='ready')return;setSource(previous=>{
    if(!previous?.annotationSelection||previous.diagramId!==diagram.id||previous.revision!==diagram.revision)return previous;
    const element=[...model.nodes,...model.edges].find(e=>e.id===previous.element?.id);if(!element)return previous;
    const refs=elementEvidence(model,element),old=previous.refs[previous.index||0];
    const index=Math.max(0,refs.findIndex(r=>r.path===old.path&&r.startLine===old.startLine&&r.locationKind===old.locationKind));
    return {...previous,refs,index,element};
  });},[model,sourceMap?.status]);
  const activeSummary=catalog.find(d=>d.id===tabs.active);
  useEffect(()=>{sourceSerial.current.invalidate();sourceAbort.current?.abort();setSource(null);setSourceError('');setSourceLoading(false);setSelection(null);setHistoryOpen(false);setVersion(null);interaction.current++;},[tabs.active]);
  useEffect(()=>{
    if(!project||!tabs.active){setDiagram(null);return;}
    const serial=loadSerial.current.next(),controller=new AbortController();setLoading(true);setError('');
    api(`/api/explore/diagrams/${tabs.active}${version?`?revision=${version}`:''}`,undefined,controller.signal).then(result=>{
      if(!loadSerial.current.current(serial)||projectRef.current!==project)return;
      setDiagram(result);const old=states.current[versionKey(result)];const chosen=result.model.nodes.find(n=>n.id===old?.selection?.id)||result.model.edges.find(e=>e.id===old?.selection?.id);setSelection(chosen||null);
    }).catch(e=>{if(e.name!=='AbortError'&&loadSerial.current.current(serial))setError(e.message);}).finally(()=>{if(loadSerial.current.current(serial))setLoading(false);});
    return()=>controller.abort();
  },[project,tabs.active,activeSummary?.revision,version]);
  useEffect(()=>{if(!host.current)return;const observer=new ResizeObserver(([entry])=>setNarrow(entry.contentRect.width-directoryWidth<720));observer.observe(host.current);return()=>observer.disconnect();},[directoryWidth]);
  useEffect(()=>{
    if(!project||!tabs.tabs.length)return;let disposed=false,running=false;const controller=new AbortController();
    async function inspect(){if(running||document.hidden)return;running=true;try{const next={},result=await api('/api/explore/diagrams/check',{diagrams:tabs.tabs.map(id=>catalog.find(x=>x.id===id)).filter(Boolean).slice(0,100).map(d=>({id:d.id,revision:d.revision}))},controller.signal);for(const item of result.checks)next[`${item.id}:${item.revision}`]=item;if(!disposed&&projectRef.current===project)setChecks(old=>({...old,...next}));}catch(e){if(!disposed&&e.name!=='AbortError')setError(e.message);}finally{running=false;}}
    inspect();const timer=setInterval(inspect,30000);window.addEventListener('focus',inspect);document.addEventListener('visibilitychange',inspect);
    return()=>{disposed=true;controller.abort();clearInterval(timer);window.removeEventListener('focus',inspect);document.removeEventListener('visibilitychange',inspect);};
  },[project,tabs.tabs.join(','),catalog.map(d=>`${d.id}:${d.revision}`).join(','),data.snapshot.id]);
  useEffect(()=>{sourceSerial.current.invalidate();sourceAbort.current?.abort();setSource(null);setSourceLoading(false);setSourceError('');},[diagram?.id,diagram?.revision]);
  useEffect(()=>{if(!diagram||!version)return;const controller=new AbortController();api(`/api/explore/diagrams/${diagram.id}/check`,{revision:version},controller.signal).then(result=>setChecks(old=>({...old,[versionKey(diagram)]:result}))).catch(()=>{});return()=>controller.abort();},[diagram?.id,version]);

  function remember(patch){if(!key)return;states.current[key]={...states.current[key],...patch};setUiTick(v=>v+1);}
  const reveal=useCallback(refs=>{setExpanded(old=>new Set([...old,...refs.flatMap(r=>parents(r.path))]));setTimeout(()=>treeHost.current?.querySelector('.tree-row.is-focused')?.scrollIntoView({block:'nearest'}),40);},[]);
  const loadSource=useCallback(async(next,start)=>{
    sourceAbort.current?.abort();const controller=new AbortController();sourceAbort.current=controller;const serial=sourceSerial.current.next(),atProject=projectRef.current,ref=next.refs[next.index||0];
    setSource(next);setSourceLoading(true);setSourceError('');reveal(next.refs);
    try{
      const begin=start||Math.max(1,ref.startLine-12),body={revision:next.revision,path:ref.path,startLine:begin,endLine:begin+249};
      const file=next.conversationId?await api('/api/explore/read',{name:'read_snapshot_source',arguments:{id:next.conversationId,snapshotId:next.snapshotId,path:ref.path,startLine:begin,endLine:begin+249}},controller.signal):await api(`/api/explore/diagrams/${next.diagramId}/source`,body,controller.signal);
      if(sourceSerial.current.current(serial)&&projectRef.current===atProject)setSource(current=>mergeSourceFile(current,next,file));
    }catch(e){if(e.name!=='AbortError'&&sourceSerial.current.current(serial))setSourceError(e.message);}finally{if(sourceSerial.current.current(serial))setSourceLoading(false);}
  },[reveal]);
  const select=useCallback((element,focusRef)=>{const d=diagramRef.current;if(!d)return;const refs=elementEvidence(d.model,element);sourceReturnFocus.current=document.activeElement;setSelection(element);
    states.current[versionKey(d)]={...states.current[versionKey(d)],selection:{id:element.id}};setUiTick(t=>t+1);
    if(refs.length)loadSource({refs,index:focusRef?Math.max(0,refs.findIndex(r=>sameEvidence(r,focusRef))):0,element,diagramId:d.id,revision:d.revision,snapshotId:d.snapshotId,annotationSelection:true});
    else {sourceSerial.current.invalidate();sourceAbort.current?.abort();setSource(null);setSourceLoading(false);}
  },[loadSource]);
  function openFile(path){
    if(diagram){const refs=model.evidence.filter(r=>r.path===path);const ref=refs[0]||{path,startLine:1,endLine:1,locationKind:'source'};loadSource({refs:refs.length?refs:[ref],index:0,diagramId:diagram.id,revision:diagram.revision,snapshotId:diagram.snapshotId,element:model.nodes.find(n=>n.evidence?.some(r=>r.path===path))});}
    else {const file=data.files.find(f=>f.id===path),hasContent=typeof file?.content==='string';setSource({refs:[{path,startLine:1,endLine:1}],index:0,snapshotId:data.snapshot.id,file:hasContent?{...file,startLine:1,endLine:file.content.split('\n').length,totalLines:file.content.split('\n').length}:null});setSourceError(hasContent?'':'此扫描未保留文件正文。请在会话中读取该文件后生成 UML。');}
  }
  useEffect(()=>{if(sourceEntry?.path)openFile(sourceEntry.path);},[sourceEntry?.serial]);
  const files=source?.refs?.map(r=>r.path)||elementEvidence(model||{nodes:[]},selection).map(r=>r.path)||[],primary=source?.refs?.[source.index||0]?.path||files[0];
  const linked=useMemo(()=>new Set(files),[files.join('|')]);
  const known=new Set((data.inventory||data.files).map(f=>f.id));
  const deleted=check?.files.filter(f=>f.status==='deleted').map(f=>f.path)||[];
  const historic=[...new Set((model?.evidence||[]).map(r=>r.path))].filter(p=>!known.has(p)||deleted.includes(p));
  useEffect(()=>()=>{sourceAbort.current?.abort();sourceSerial.current.invalidate();loadSerial.current.invalidate();},[]);
  useEffect(()=>{if(narrow)setDirectoryOpen(false);},[narrow]);
  function closeSource(){sourceSerial.current.invalidate();sourceAbort.current?.abort();setSource(null);setSourceLoading(false);setSourceError('');requestAnimationFrame(()=>{const prior=sourceReturnFocus.current;const target=host.current.querySelector('.standard-uml')||(prior?.isConnected&&prior!==document.body&&!host.current?.querySelector('.uml-inspector')?.contains(prior)?prior:[...host.current.querySelectorAll('.standard-uml-image [data-element]')].find(el=>el.dataset.element===selection?.id)||host.current.querySelector('.uml-node.is-selected'));target?.focus({preventScroll:true});});}
  function ask(question){drawer.setOpen(true);chatRequest.current?.({question,prepare:true});}
  async function update(){drawer.setOpen(true);await chatRequest.current?.({question:`请根据当前代码更新 UML「${model.title}」，保留其类型与用途，并说明变化。`,update:true});}
  function activate(id){interaction.current++;setTabs(old=>({tabs:[...new Set([...old.tabs,id])],active:id}));setVersion(null);setListOpen(false);}
  async function openList(){setListOpen(v=>!v);setHistoryOpen(false);try{const result=await api('/api/explore/diagrams/drafts');setDrafts(result.drafts);}catch(e){setError(e.message);}}
  async function openHistory(){setHistoryOpen(v=>!v);setListOpen(false);try{const result=await api(`/api/explore/diagrams/${diagram.id}/versions`);if(diagramRef.current?.id===diagram.id)setVersions(result.versions);}catch(e){setError(e.message);}}
  async function generated(ids){await refreshCatalog();setTabs(old=>({tabs:[...new Set([...old.tabs,...ids])],active:runInteraction.current===interaction.current?ids[0]||old.active:old.active}));}
  const context=diagram?{id:diagram.id,expectedRevision:diagram.current_revision,title:model.title,snapshotId:diagram.snapshotId}:null;
  return <div className={`uml-workspace ${narrow?'is-narrow':''} ${directoryOpen?'directory-open':'directory-closed'}`} ref={host} style={{'--uml-directory-width':`${directoryWidth}px`}}>
    {directoryOpen&&narrow&&<button className="uml-directory-scrim" aria-label="收起目录" onClick={()=>setDirectoryOpen(false)}/>}
    <aside className="uml-directory" ref={treeHost} hidden={!directoryOpen}><header><strong>项目文件</strong><span title="选中图节点后自动展开并高亮文件"><Link2 size={13}/>跟随图中选择</span><button className="icon-button" aria-label="收起项目目录" onClick={()=>{setDirectoryOpen(false);try{localStorage.setItem('strata:uml:directory','false');}catch{}}}><PanelLeftClose size={15}/></button></header>
      <Tree data={data} includeConfigs hiddenFiles={deleted} expanded={expanded} setExpanded={setExpanded} linked={linked} focusId={primary} onFile={openFile}/>
      {!!historic.length&&<section className="uml-historical-files"><strong><FileClock size={13}/>历史快照文件</strong>{historic.map(path=><button className={primary===path?'is-focused':''} key={path} title={path} onClick={()=>openFile(path)}>{path.split('/').at(-1)}<small>当前目录中不存在</small></button>)}</section>}
    </aside>
    {directoryOpen&&!narrow&&<div className="uml-directory-resize" role="separator" aria-label="调整目录宽度" aria-orientation="vertical" aria-valuemin={180} aria-valuemax={400} aria-valuenow={directoryWidth} tabIndex={0}
      onPointerDown={e=>{resize.current={x:e.clientX,width:directoryWidth};e.currentTarget.setPointerCapture(e.pointerId);}} onPointerMove={e=>{if(resize.current)setDirectoryWidth(Math.max(180,Math.min(400,resize.current.width+e.clientX-resize.current.x)));}} onPointerUp={()=>{resize.current=null;}} onPointerCancel={()=>{resize.current=null;}}
      onDoubleClick={()=>setDirectoryWidth(240)} onKeyDown={e=>{if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();setDirectoryWidth(w=>Math.max(180,Math.min(400,w+(e.key==='ArrowRight'?24:-24))));}}}/>}
    <main className="uml-main">
      <div className="uml-tabs-bar"><button className="icon-button uml-directory-toggle" aria-label={directoryOpen?'收起项目目录':'展开项目目录'} onClick={()=>setDirectoryOpen(v=>!v)}><PanelLeftOpen size={16}/></button>
        <div className="uml-tabs" role="tablist" aria-label="项目 UML 图">{tabs.tabs.map(id=>{const item=catalog.find(d=>d.id===id);if(!item)return null;const changed=checks[`${id}:${item.revision}`];return <div className={`uml-tab ${tabs.active===id?'is-active':''}`} key={id}>
          <button role="tab" id={'tab-'+id} aria-controls="uml-tab-panel" aria-selected={tabs.active===id} onClick={()=>activate(id)} onKeyDown={e=>{const at=tabs.tabs.indexOf(id);if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const next=e.key==='Home'?tabs.tabs[0]:e.key==='End'?tabs.tabs.at(-1):tabs.tabs[(at+(e.key==='ArrowRight'?1:tabs.tabs.length-1))%tabs.tabs.length];activate(next);document.getElementById('tab-'+next)?.focus();}}} title={item.purpose}><span>{item.title}</span><small>{UML_TYPES[item.type]}</small>{changed&&(changed.status!=='current'||changed.analyzerChanged)&&<FileClock className="uml-tab-stale" size={13} aria-label="源码或分析器有变化"/>}</button>
          <button className="uml-tab-close" aria-label={'关闭标签 '+item.title} onClick={()=>{interaction.current++;setTabs(old=>closeTab(old,id));}}><X size={13}/></button></div>;})}</div>
        <div className="uml-tab-tools"><button className="icon-button" title="项目图列表（关闭标签不会删除图）" aria-label="项目图列表" aria-expanded={listOpen} onClick={openList}><List size={17}/></button>{diagram&&<button className="icon-button" title="图版本" aria-label="图版本" aria-expanded={historyOpen} onClick={openHistory}><History size={16}/></button>}<button className="icon-button" title="重新扫描项目" aria-label="重新扫描项目" disabled={busy} onClick={onRefresh}><RefreshCw size={15} className={busy?'spin':''}/></button></div>
      </div>
      {listOpen&&<section className="uml-document-menu" aria-label="项目图列表"><header><strong>项目共享图集</strong><button className="icon-button" aria-label="关闭图列表" onClick={()=>setListOpen(false)}><X size={15}/></button></header>{catalog.map(d=><button key={d.id} onClick={()=>activate(d.id)}><strong>{d.title}<small>{UML_TYPES[d.type]} · v{d.revision}</small></strong><span>{d.purpose}</span></button>)}{!catalog.length&&<p>在右侧会话描述想了解的内容，Agent 会生成 UML。</p>}
        {!!drafts.length&&<details><summary>未发布草稿（{drafts.length}）</summary>{drafts.map(d=><div key={d.runId}>{d.diagrams.map(x=><p key={x.id}>{x.model.title} · {UML_TYPES[x.model.type]}</p>)}<button onClick={()=>{ask(`请调用 get_diagram_draft 读取草稿，再读取项目图集最新版本并重新查询源码，恢复任务 ${d.runId} 的未发布 UML 草稿。`);}}>在会话中恢复</button><details><summary>查看草稿数据</summary><pre>{JSON.stringify(d.diagrams,null,2)}</pre></details></div>)}</details>}
      </section>}
      {historyOpen&&<section className="uml-document-menu" aria-label="图版本列表"><header><strong>图版本</strong><button className="icon-button" aria-label="关闭版本列表" onClick={()=>setHistoryOpen(false)}><X size={15}/></button></header>{versions.map(v=><button key={v.revision} onClick={()=>{sourceSerial.current.invalidate();sourceAbort.current?.abort();setSource(null);setVersion(v.revision===diagram.current_revision?null:v.revision);setHistoryOpen(false);}}><strong>v{v.revision}{v.revision===diagram.current_revision?' · 最新':''}</strong><span>{new Date(v.createdAt).toLocaleString('zh-CN')} · {v.snapshotId.slice(0,8)}</span></button>)}</section>}
      <div className="uml-purpose"><Info size={15}/><strong>用途</strong><span title={model?.purpose}>{model?.purpose||'通过会话生成 UML，再沿图中节点与连线查看源码依据。'}</span>{diagram&&<button className={`text-button uml-freshness ${check?.status==='stale'?'is-stale':''}`} title={freshnessText(check)} onClick={update} disabled={loading||Boolean(version&&version!==diagram.current_revision)}><FileClock size={14}/>{version&&version!==diagram.current_revision?`历史 v${version}`:check?.status==='stale'?'源码有变化 · 更新':check?.analyzerChanged?'重新分析':'根据当前代码更新'}</button>}</div>
      {model&&model.type!=='legacy'&&<div className="uml-view-toolbar"><div className="uml-segmented" role="group" aria-label="UML 视图">{[['interactive','交互视图'],['standard','标准 UML']].map(([value,label])=><button key={value} aria-pressed={viewMode===value} onClick={()=>setViewMode(value)}>{label}</button>)}</div><span>源码标签</span><div className="uml-segmented" role="group" aria-label="源码标签显示">{[['folded','折叠'],['expanded','展开']].map(([value,label])=><button key={value} aria-pressed={tagMode===value} onClick={()=>setTagMode(value)}>{label}</button>)}</div></div>}
      {error&&<div className="uml-error" role="alert">{error}<button className="text-button" onClick={()=>{setError('');refreshCatalog().catch(e=>setError(e.message));}}>重试</button></div>}
      <section className="uml-tab-panel" id="uml-tab-panel" role="tabpanel" aria-labelledby={tabs.active?'tab-'+tabs.active:undefined}>
        {loading?<div className="uml-empty"><LoaderCircle className="spin"/>读取图版本…</div>:model?model.type==='legacy'?<ReactFlowProvider><ExplorationGraph view={model.legacy} onSource={node=>{const ref=model.evidence.find(r=>r.path===node.path&&r.startLine===node.range?.start?.[0])||{path:node.path,startLine:node.range?.start?.[0]||1,endLine:node.range?.start?.[0]||1};loadSource({refs:[ref],index:0,element:{label:node.name,explanation:node.reason||model.explanation},diagramId:diagram.id,revision:diagram.revision,snapshotId:diagram.snapshotId});}}/></ReactFlowProvider>:viewMode==='standard'?<StandardUml key={key} document={diagram} model={model} state={currentState} onState={remember} onSelect={select} selection={selection}/>:<UmlGraph key={key} model={model} state={currentState} tagMode={tagMode} onState={remember} onSelect={select} externalSelection={selection}/>:<div className="uml-empty"><GitBranch size={40}/><h2>从一个问题，开始理解代码</h2><p>和 Agent 交流，生成有类型、用途和源码依据的 UML。</p><button className="button primary" onClick={()=>drawer.setOpen(true)}>打开会话</button>{catalog.length>0&&<button className="text-button" onClick={openList}>重新打开已有图</button>}</div>}
      </section>
      {source&&<SourceInspector source={source} loading={sourceLoading} error={sourceError} height={sheetHeight} setHeight={setSheetHeight} onClose={closeSource} onEvidence={index=>loadSource({...source,index,file:null})} onPage={start=>loadSource(source,start)} onQuestion={ask} onCitation={node=>{const line=node.range?.start?.[0]||1;const existing=source.refs.findIndex(r=>r.path===node.path&&r.startLine===line);loadSource(existing>=0?{...source,index:existing,file:null}:{...source,refs:[...source.refs,{path:node.path,startLine:line,endLine:node.range?.end?.[0]||line,locationKind:"source"}],index:source.refs.length,file:null});}} check={check} tagMode={tagMode} sourceMap={sourceMap} retryMap={()=>setMapRetry(n=>n+1)}/>}
    </main>
    {renderChat({chatOnly:true,diagramContext:context,requestRef:chatRequest,onRunStart:()=>{runInteraction.current=interaction.current;},onDiagrams:generated,onExternalSource:(node,conversationId,snapshotId)=>loadSource({refs:[{path:node.path,startLine:node.range?.start?.[0]||1,endLine:node.range?.end?.[0]||node.range?.start?.[0]||1}],index:0,element:{label:node.path},conversationId,snapshotId})})}
  </div>;
}
