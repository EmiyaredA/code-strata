import { TYPE_OPTIONS } from './notation.js';
import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { SelectMenu } from './SelectMenu.jsx';
import { X, Plus, Trash2, RotateCcw, RefreshCw, FileClock, LoaderCircle, Search } from 'lucide-react';
import { explorationApi as api, loadConversation } from './exploration-api.js';
import { UML_TYPES, freshnessText } from './uml-model.js';
import { diagramCheckLabel, managementRequest } from './diagram-management.js';

export function DiagramManager({project,refreshKey,checks,onItems,onOpen,onAction,onClose,drafts,onDraft}) {
  const [state,setState]=useState('active'),[query,setQuery]=useState(''),[items,setItems]=useState([]),[next,setNext]=useState(null),[loading,setLoading]=useState(false),[error,setError]=useState(''),[retry,setRetry]=useState(0);
  const gate=useRef(0),abort=useRef(null),search=useRef(null),closeRef=useRef(onClose);closeRef.current=onClose;
  useEffect(()=>{const previous=document.activeElement;search.current?.focus();const key=e=>{if(e.key==='Escape'&&!document.querySelector('.uml-action-dialog')){e.stopImmediatePropagation();closeRef.current();}};document.addEventListener('keydown',key,true);return()=>{document.removeEventListener('keydown',key,true);if(previous?.isConnected)previous.focus?.();};},[]);
  async function read(offset=0) {
    abort.current?.abort();const controller=new AbortController();abort.current=controller;const serial=++gate.current;
    setLoading(true);setError('');
    try {const result=await api(`/api/explore/diagrams?state=${state}&q=${encodeURIComponent(query)}&offset=${offset}`,undefined,controller.signal);
      if(serial!==gate.current)return;setItems(old=>offset?[...old,...result.diagrams]:result.diagrams);setNext(result.nextOffset);
    }catch(e){if(e.name!=='AbortError'&&serial===gate.current)setError(e.message);}finally{if(serial===gate.current)setLoading(false);}
  }
  useEffect(()=>{const timer=setTimeout(()=>read(),query?180:0);return()=>{clearTimeout(timer);++gate.current;abort.current?.abort();};},[project,state,query,refreshKey,retry]);
  useEffect(()=>{onItems(state==='active'?items:[]);},[items,state,onItems]);
  useEffect(()=>()=>onItems([]),[onItems]);
  return <section className="uml-manager" role="dialog" aria-modal="false" aria-label="图管理" onKeyDown={e=>{if(e.key==='Escape'){e.stopPropagation();onClose();}}}>
    <header><div><strong>图管理</strong><small>项目共享 · 关闭标签不会删除图</small></div><button className="icon-button" aria-label="关闭图管理" onClick={onClose}><X size={16}/></button></header>
    <div className="uml-manager-tools"><div className="uml-segmented" role="group" aria-label="图集范围">{[['active','全部图'],['trashed','回收站']].map(([value,label])=><button key={value} aria-pressed={state===value} onClick={()=>{setItems([]);setState(value);}}>{label}</button>)}</div><button className="button primary" onClick={()=>onAction({kind:'create'})}><Plus size={14}/>新增图</button></div>
    <label className="uml-manager-search"><Search size={15}/><input ref={search} aria-label="搜索图名称" value={query} maxLength={200} placeholder="搜索图名称" onChange={e=>{setItems([]);setQuery(e.target.value);}}/></label>
    <div className="uml-manager-list" aria-busy={loading}>
      {items.map(d=><article key={d.id}><div className="uml-manager-item-title"><strong>{d.title}</strong><small>{UML_TYPES[d.type]} · v{d.revision}</small></div><p>{d.purpose}</p>
        <div className="uml-manager-meta"><time>{new Date(d.updatedAt).toLocaleString('zh-CN')}</time>{state==='active'?<span className={checks[`${d.id}:${d.revision}`]?.status==='stale'?'is-stale':''} title={freshnessText(checks[`${d.id}:${d.revision}`])}><FileClock size={12}/>{diagramCheckLabel(checks[`${d.id}:${d.revision}`])}</span>:<span>删除于 {new Date(d.deletedAt).toLocaleString('zh-CN')}</span>}</div>
        <div className="uml-manager-actions">{state==='active'?<><button className="text-button" onClick={()=>onOpen(d.id)}>打开</button><button className="text-button" onClick={()=>onAction({kind:'update',item:d})}><RefreshCw size={12}/>根据当前代码更新</button><button className="text-button danger" onClick={()=>onAction({kind:'trash',item:d})}><Trash2 size={12}/>删除</button></>:<button className="text-button" onClick={()=>onAction({kind:'restore',item:d})}><RotateCcw size={12}/>恢复</button>}</div>
      </article>)}
      {!loading&&!items.length&&!error&&<p className="uml-manager-empty">{query?'没有匹配的图':state==='trashed'?'回收站为空':'还没有图，点击“新增图”开始。'}</p>}
      {loading&&<p className="uml-manager-empty" role="status"><LoaderCircle size={14} className="spin"/>正在读取图集…</p>}
      {error&&<p className="uml-manager-empty" role="alert">{error}<button className="text-button" onClick={()=>setRetry(n=>n+1)}>重试</button></p>}
      {next!==null&&!loading&&<button className="button uml-load-more" onClick={()=>read(next)}>加载更多</button>}
      {!!drafts.length&&state==='active'&&<details className="uml-manager-drafts"><summary>未发布草稿（{drafts.length}）</summary>{drafts.map(d=><div key={d.runId}><p>{d.diagrams.map(x=>x.model.title).join('、')}</p><button className="text-button" onClick={()=>onDraft(d.runId)}>在会话中恢复</button></div>)}</details>}
    </div>
  </section>;
}

export function DiagramActionDialog({action,project,onClose,onLaunch,onComplete,onChanged}) {
  const kind=action.kind,updating=kind==='update',generating=updating||kind==='create';
  const [question,setQuestion]=useState(''),[type,setType]=useState('auto'),[document,setDocument]=useState(null),[check,setCheck]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[run,setRun]=useState(null),[retry,setRetry]=useState(0),[loading,setLoading]=useState(updating);
  const live=useRef(true),submitLock=useRef(false),first=useRef(null),closeRef=useRef(onClose);closeRef.current=onClose;
  useEffect(()=>{live.current=true;const prior=globalThis.document.activeElement;first.current?.focus();const key=e=>{if(e.key==='Escape'&&!e.target.closest?.('[role="combobox"][aria-expanded="true"]')){e.stopImmediatePropagation();closeRef.current();}};globalThis.document.addEventListener('keydown',key,true);return()=>{live.current=false;globalThis.document.removeEventListener('keydown',key,true);prior?.isConnected&&prior.focus?.();};},[]);
  useEffect(()=>{if(!updating)return;const controller=new AbortController();setLoading(true);setError('');
    Promise.all([api(`/api/explore/diagrams/${action.item.id}`,undefined,controller.signal),api(`/api/explore/diagrams/${action.item.id}/check`,{},controller.signal)]).then(([doc,status])=>{if(!controller.signal.aborted){setDocument({...doc,...doc.model,revision:doc.current_revision});setCheck(status);}}).catch(e=>{if(e.name!=='AbortError')setError(e.message);}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});return()=>controller.abort();
  },[project,action.item?.id,retry]);
  useEffect(()=>{if(!run)return;let timer,disposed=false;const controller=new AbortController();
    async function poll(){try{const result=await loadConversation(run.conversationId,controller.signal);if(disposed)return;
      if(result.run?.id===run.runId&&result.run.status!=='running'){
        if(result.run.status==='completed'){const message=result.history.messages.find(m=>m.run_id===run.runId&&m.kind==='diagrams');if(message?.content.diagramIds?.length){await onComplete(message.content.diagramIds);if(!disposed)onClose();return;} }
        setBusy(false);setRun(null);submitLock.current=false;
        setError(result.run.error||'生成未完成，原图已保留，可重试。');return;
      }
    }catch(e){if(disposed)return;setError(`状态读取失败，任务可能仍在运行：${e.message}`);}if(!disposed)timer=setTimeout(poll,1200);}
    poll();return()=>{disposed=true;controller.abort();clearTimeout(timer);};
  },[run?.runId]);
  async function submit(e){e.preventDefault();if(submitLock.current)return;submitLock.current=true;setBusy(true);setError('');
    try {if(generating){const request=managementRequest(kind,question,type,document);const started=await onLaunch(request);if(live.current)setRun(started);}
      else {const d=action.item;await api(`/api/explore/diagrams/${d.id}/${kind}`,{expectedRevision:d.revision,lifecycleVersion:d.lifecycleVersion});await onChanged();if(live.current)onClose();}
    }catch(e){if(live.current){setError(e.message);setBusy(false);submitLock.current=false;}}
  }
  async function cancel(){try{await api(`/api/explore/conversations/${run.conversationId}/cancel`,{});}catch(e){setError(e.message);}}
  const title={create:'新增图',update:'根据当前代码更新',trash:'移入回收站',restore:'恢复图'}[kind];
  return createPortal(<div className="uml-action-scrim"><section className="uml-action-dialog" role="dialog" aria-modal="true" aria-label={title} onKeyDown={e=>{if(e.key==='Tab'){const nodes=[...e.currentTarget.querySelectorAll('button,input,textarea,select')].filter(n=>!n.disabled);const first=nodes[0],last=nodes.at(-1);if(e.shiftKey&&globalThis.document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&globalThis.document.activeElement===last){e.preventDefault();first?.focus();}}}}>
    <header><strong>{title}</strong><button className="icon-button" aria-label="关闭图操作" onClick={onClose}><X size={17}/></button></header>
    <form onSubmit={submit}>
      {updating&&<div className="uml-update-target"><strong>{document?.title||action.item.title}</strong><small>{UML_TYPES[document?.type||action.item.type]} · 当前 v{document?.revision||action.item.revision}</small><p>{document?.purpose||action.item.purpose}</p>
        {loading?<p role="status">正在读取图与源码变化…</p>:<><span className="uml-update-status">{diagramCheckLabel(check)}</span><ul>{check?.files.filter(f=>f.status!=='current').map(f=><li key={f.path}><code>{f.path}</code> · {({modified:'已修改',deleted:'已删除',error:'检查失败'})[f.status]}</li>)}</ul><small>检查仅覆盖旧图的关联文件；可随时重新生成以纳入新增实现。</small></>}
        {(document?.type||action.item.type)==='legacy'&&<p className="uml-update-note">将转换为合适的 UML 类型，原阅读图保留在版本历史中。</p>}
      </div>}
      {generating?<><label>{updating?'补充要求（可选）':'想了解什么'}<textarea ref={first} value={question} onChange={e=>setQuestion(e.target.value)} required={!updating} maxLength={8000} rows={4} disabled={busy} placeholder={updating?'例如：补充新增分支，重点说明数据流变化':'例如：画出配置迁移流程，说明为何先备份再发布'}/></label>
        {!updating&&<label>图类型<SelectMenu label="图类型" value={type} onChange={setType} disabled={busy} className="uml-diagram-type-trigger" options={[{value:'auto',label:'自动选择'},...TYPE_OPTIONS]}/></label>}
        <p className="uml-action-help">使用当前选定 Agent 和当前代码生成{updating?'新版本':'一张新图'}，结果及进度记录在新会话中。{updating?'旧版本和生成时源码继续保留。':''}</p></>:<p>{kind==='trash'?`将「${action.item.title}」移入回收站？图版本和源码快照保留，可随时恢复。`:`恢复「${action.item.title}」到项目图集，恢复后不会自动打开标签。`}</p>}
      {error&&<div className="uml-action-error" role="alert">{error}{updating&&!busy&&<button type="button" className="text-button" onClick={()=>setRetry(n=>n+1)}>重新读取</button>}</div>}
      {run&&<p role="status"><LoaderCircle className="spin" size={14}/>正在生成，原图保持可用。可关闭此窗在会话中查看进度。</p>}
      <footer>{run?<button type="button" className="button" onClick={cancel}>停止生成</button>:<button ref={!generating?first:undefined} type="button" className="button" onClick={onClose}>取消</button>}<button type="submit" className={`button ${kind==='trash'?'danger':'primary'}`} disabled={busy||loading||(updating&&!document)}>{busy?'处理中…':({create:'生成新图',update:'生成新版本',trash:'移入回收站',restore:'恢复'})[kind]}</button></footer>
    </form>
  </section></div>,globalThis.document.body);
}
