import React, {useEffect, useLayoutEffect, useRef, useState} from 'react';
import './panel-resize.css';
const MIN_RIGHT=280, MIN_LEFT=360;
export function usePanelResize(name, defaultWidth=360) {
  const ref=useRef(null), [width,setWidth]=useState(()=>{
    try {const saved=Number(localStorage.getItem('code-strata:panel:'+name));return saved>=MIN_RIGHT?saved:defaultWidth;} catch {return defaultWidth;}
  }), [bounds,setBounds]=useState({max:800,enabled:true}), [handleLeft,setHandleLeft]=useState(0);
  const widthRef=useRef(width);widthRef.current=width;
  useLayoutEffect(()=>{
    const root=ref.current;if(!root)return;
    function measure(){
      const rect=root.getBoundingClientRect(), style=getComputedStyle(root), inner=rect.width-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight);
      if(!rect.width)return;
      const max=Math.max(MIN_RIGHT,inner-MIN_LEFT-16), enabled=inner>=MIN_LEFT+MIN_RIGHT+16;
      setBounds({max,enabled});
      const clamped=Math.max(MIN_RIGHT,Math.min(max,widthRef.current));
      if(enabled&&clamped!==widthRef.current)setWidth(clamped);
      const panel=root.querySelector(':scope > aside');
      if(panel)setHandleLeft(panel.getBoundingClientRect().left-rect.left-16);
    }
    const observer=new ResizeObserver(measure);observer.observe(root);
    const right=root.querySelector(':scope > aside');if(right)observer.observe(right);
    measure();return()=>observer.disconnect();
  },[name,width]);
  const update=next=>setWidth(Math.max(MIN_RIGHT,Math.min(bounds.max,next)));
  const persist=()=>{try{localStorage.setItem('code-strata:panel:'+name,String(widthRef.current));}catch{}};
  return {ref,width,update,persist,bounds,handleLeft,style:bounds.enabled?{gridTemplateColumns:`minmax(${MIN_LEFT}px,1fr) ${width}px`}:undefined};
}
export function PanelResize({split}) {
  const drag=useRef(null);
  useEffect(()=>()=>{document.documentElement.classList.remove('is-resizing-panels');},[]);
  if(!split.bounds.enabled)return null;
  function end(e){if(!drag.current)return;drag.current=null;if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId);document.documentElement.classList.remove('is-resizing-panels');split.persist();}
  return <div className="panel-resize-handle" style={{left:split.handleLeft}} role="separator" aria-label="调整左右面板宽度" aria-orientation="vertical" aria-valuemin={MIN_RIGHT} aria-valuemax={Math.round(split.bounds.max)} aria-valuenow={Math.round(split.width)} tabIndex={0} title="拖动调整宽度；双击恢复默认"
    onPointerDown={e=>{if(e.button!==0)return;e.preventDefault();drag.current={x:e.clientX,width:split.width};e.currentTarget.setPointerCapture(e.pointerId);document.documentElement.classList.add('is-resizing-panels');}}
    onPointerMove={e=>{if(drag.current)split.update(drag.current.width+drag.current.x-e.clientX);}}
    onPointerUp={end} onPointerCancel={end}
    onDoubleClick={()=>{split.update(360);setTimeout(split.persist,0);}}
    onKeyDown={e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();split.update(split.width+(e.key==='ArrowLeft'?24:-24));setTimeout(split.persist,0);}if(e.key==='Home'){e.preventDefault();split.update(MIN_RIGHT);setTimeout(split.persist,0);}}}><span/></div>;
}
