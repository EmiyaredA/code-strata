import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Download, Minus, Plus, Maximize, LoaderCircle } from 'lucide-react';
import { explorationApi as api } from './exploration-api.js';
import { keepStandardVisible } from './standard-viewport.js';

export function StandardUml({ document: doc, model, state, onState, onSelect, selection }) {
  const [render,setRender]=useState(null),[runtime,setRuntime]=useState(null),[error,setError]=useState(''),[retry,setRetry]=useState(0),[busy,setBusy]=useState(false);
  const [viewport,setViewport]=useState(state?.standardViewport||{x:20,y:20,zoom:1});
  const viewportRef=useRef(viewport);viewportRef.current=viewport;
  const host=useRef(null),image=useRef(null),drag=useRef(null),callbacks=useRef({onState,onSelect,model});callbacks.current={onState,onSelect,model,selection};
  const move = next => {setViewport(next);callbacks.current.onState({standardViewport:next});};
  useEffect(()=>{const controller=new AbortController();let timer;
    setRender(null);setError('');setBusy(true);
    async function read(){try{
      const status=await api('/api/explore/uml-runtime',undefined,controller.signal);setRuntime(status);
      if(status.status==='installing'){timer=setTimeout(read,1000);return;}
      if(status.status!=='ready'){setBusy(false);return;}
      const result=await api(`/api/explore/diagrams/${doc.id}/render`,{revision:doc.revision},controller.signal);
      if(!controller.signal.aborted){setRender(result);setBusy(false);}
    }catch(e){if(!controller.signal.aborted){setError(e.message);setBusy(false);}}}
    read();return()=>{controller.abort();clearTimeout(timer);};
  },[doc.id,doc.revision,retry]);
  const markup=useMemo(()=>{if(!render)return '';const svg=new DOMParser().parseFromString(render.svg,'image/svg+xml');svg.documentElement.setAttribute('role','group');svg.documentElement.setAttribute('aria-label','标准 UML 元素');for(const el of svg.querySelectorAll('[data-element]')){
    el.classList.toggle('is-selected',el.dataset.element===selection?.id);
    const element=[...model.nodes,...model.edges].find(n=>n.id===el.dataset.element);
    el.setAttribute('aria-label',`查看源码：${element?.label||'关系依据'}`);
    if(element?.evidence?.length){const title=svg.createElementNS('http://www.w3.org/2000/svg','title');title.textContent=element.evidence.map(r=>`${r.path}${r.symbol?' · '+r.symbol.name+'()':''}:${r.startLine}`).join('\n');el.prepend(title);}
  }return new XMLSerializer().serializeToString(svg.documentElement);},[render,selection,model]);
  function choose(event){const target=event.target.closest('[data-element]');if(!target)return;
    event.preventDefault();event.stopPropagation();const element=[...callbacks.current.model.nodes,...callbacks.current.model.edges].find(n=>n.id===target.dataset.element);if(element)callbacks.current.onSelect(element);
  }
  function fit(readable=false){const svg=image.current?.querySelector('svg');if(!svg||!host.current)return;const box=svg.viewBox.baseVal;const zoom=Math.max(readable?.8:.1,Math.min(1,(host.current.clientWidth-40)/box.width,(host.current.clientHeight-40)/box.height));let x=(host.current.clientWidth-box.width*zoom)/2,y=readable?20:(host.current.clientHeight-box.height*zoom)/2;
    if(readable&&selection){const selected=[...svg.querySelectorAll('[data-element]')].find(el=>el.dataset.element===selection.id);if(selected){const bounds=selected.getBBox();y=Math.max(20,host.current.clientHeight/2)-(bounds.y+bounds.height/2)*zoom;}}
    move({x:Math.max(20,x),y,zoom});}
  useEffect(()=>{if(render&&!state?.standardViewport)requestAnimationFrame(()=>fit(true));},[render]);
  useEffect(()=>{if(!host.current||!render)return;let old={w:host.current.clientWidth,h:host.current.clientHeight};const observer=new ResizeObserver(([entry])=>{const {width:w,height:h}=entry.contentRect;
    const previous=viewportRef.current,svg=image.current?.querySelector('svg');if(!svg)return;
    const selected=[...svg.querySelectorAll('[data-element]')].find(el=>el.dataset.element===callbacks.current.selection?.id),box=selected?.getBBox();
    const next=keepStandardVisible({...previous,x:previous.x+(w-old.w)/2,y:previous.y+(h-old.h)/2},{width:w,height:h},svg.viewBox.baseVal,box?{x:box.x+box.width/2,y:box.y+box.height/2}:null);
    if(next.x!==previous.x||next.y!==previous.y)move(next);old={w,h};});observer.observe(host.current);return()=>observer.disconnect();},[render]);
  async function install(){setError('');try{await api('/api/explore/uml-runtime',{install:true});setRetry(n=>n+1);}catch(e){setError(e.message);}}
  function save(extension,content,type){const url=URL.createObjectURL(new Blob([content],{type}));const a=document.createElement('a');a.href=url;a.download=`${model.title.replace(/[\\/:*?"<>|]/g,'_')}.${extension}`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  return <div className="standard-uml" ref={host} tabIndex={0} aria-label="标准 UML 画布"
    onPointerDown={e=>{if(e.button||e.target.closest('button,[data-element]'))return;drag.current={x:e.clientX,y:e.clientY,viewport};e.currentTarget.setPointerCapture(e.pointerId);}}
    onPointerMove={e=>{if(drag.current)move({...viewport,x:drag.current.viewport.x+e.clientX-drag.current.x,y:drag.current.viewport.y+e.clientY-drag.current.y});}}
    onPointerUp={()=>{drag.current=null;}} onPointerCancel={()=>{drag.current=null;}}>
    {render?<><div className="standard-uml-image" ref={image} style={{transform:`translate(${viewport.x}px,${viewport.y}px) scale(${viewport.zoom})`}}
      onClick={choose} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){choose(e);}}} dangerouslySetInnerHTML={{__html:markup}}/>
      <div className="standard-uml-controls"><button aria-label="缩小标准图" onClick={()=>move({...viewport,zoom:Math.max(.1,viewport.zoom/1.2)})}><Minus size={15}/></button><span>{Math.round(viewport.zoom*100)}%</span><button aria-label="放大标准图" onClick={()=>move({...viewport,zoom:Math.min(3,viewport.zoom*1.2)})}><Plus size={15}/></button><button aria-label="适应标准图" onClick={()=>fit()}><Maximize size={15}/></button><button onClick={()=>save('svg',render.svg,'image/svg+xml')}><Download size={14}/>SVG</button><button onClick={()=>save('puml',render.source,'text/plain;charset=utf-8')}>PlantUML</button></div>
    </>:<div className="uml-empty">{busy?<><LoaderCircle className="spin"/>{runtime?.status==='installing'?<><strong>{runtime.phase}</strong><span>{runtime.total?Math.round(runtime.received/runtime.total*100)+'%':'正在准备本地依赖…'}</span></>:'正在渲染标准 UML…'}</>:<><strong>{error||runtime?.message||'标准 UML 需要本地渲染运行时'}</strong><p>Java 21 与 PlantUML 安装在应用私有目录，安装后离线渲染。</p>{runtime?.status!=='ready'?<button className="button" onClick={install} disabled={runtime?.status==='unsupported'}>{runtime?.status==='failed'?'重试安装':'安装本地渲染运行时'}</button>:<button className="button" onClick={()=>setRetry(n=>n+1)}>重试渲染</button>}<small>可随时切回交互视图；不会调用模型。</small></>}</div>}
  </div>;
}
