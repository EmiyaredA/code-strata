import React, { useEffect, useId, useState } from 'react';
import { createPortal } from 'react-dom';
import { sourceGroups, locationLabel } from './source-tags.js';

export function SourceTags({ refs, mode = 'folded', onChoose, limit = Infinity }) {
  const [preview,setPreview]=useState(null),tooltipId=useId();
  useEffect(()=>setPreview(null),[mode,refs]);
  const groups = sourceGroups(refs);
  if (!groups.length) return null;
  const invoke = (event, ref) => { event.preventDefault();event.stopPropagation();setPreview(null);onChoose?.(ref); };
  const hint=(ref)=>({onMouseEnter:e=>show(e,ref),onFocus:e=>show(e,ref),onMouseLeave:()=>setPreview(null),onBlur:()=>setPreview(null),'aria-describedby':preview?tooltipId:undefined});
  function show(event,ref){const box=event.currentTarget.getBoundingClientRect();const width=Math.min(360,window.innerWidth-24);setPreview({ref,width,left:Math.max(12,Math.min(box.left,window.innerWidth-width-12)),top:Math.max(12,Math.min(box.bottom+7,window.innerHeight-120))});}
  return <><div className={`source-tags nodrag nopan ${mode === 'expanded' ? 'is-expanded' : 'is-folded'}`} aria-label="关联源码">
    {groups.slice(0, limit).map(file => <div key={file.path} className="source-file-tag" role="group" aria-label={`文件 ${file.path}`}>
      <button className="source-file-name" {...hint(file.refs[0])} aria-label={`查看文件 ${file.path}`} onClick={e=>invoke(e,file.refs[0])}>{mode === 'expanded' ? file.name : file.prefix}</button>
      {file.functions.length>0 && <div className="source-function-tags">{file.functions.slice(0, Number.isFinite(limit) ? 2 : Infinity).map(f => <button key={f.key} className="source-function-tag" {...hint(f.ref)} aria-description={`函数 · ${f.ref.symbol.kind}`} aria-label={`${locationLabel(f.ref)} ${file.path} ${f.name} 第 ${f.ref.startLine} 行`} onClick={e=>invoke(e,f.ref)}>{mode === 'expanded' ? f.name : f.prefix}</button>)}{Number.isFinite(limit)&&file.functions.length>2&&<button className="source-more" aria-label={`查看全部 ${file.functions.length} 个函数依据`} onClick={e=>invoke(e,file.refs[0])}>+{file.functions.length-2}</button>}</div>}
    </div>)}
    {groups.length>limit&&<button className="source-more" aria-label={`查看全部 ${groups.length} 个文件依据`} onClick={e=>invoke(e,groups[limit].refs[0])}>+{groups.length-limit}</button>}
  </div>{preview&&createPortal(<div id={tooltipId} className="source-tag-tooltip" role="tooltip" style={{left:preview.left,top:preview.top,maxWidth:preview.width}}><strong>{preview.ref.symbol?.name?preview.ref.symbol.name+'()':preview.ref.path.split('/').at(-1)}</strong><span>{preview.ref.path}</span><small>{preview.ref.symbol?`函数 (${preview.ref.symbol.kind}) · `:"文件 · "}{locationLabel(preview.ref)} · 第 {preview.ref.startLine}–{preview.ref.endLine} 行</small></div>,document.body)}</>;
}
