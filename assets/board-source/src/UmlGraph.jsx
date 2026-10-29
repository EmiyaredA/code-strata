import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ReactFlow, ReactFlowProvider, Background, Controls, ControlButton, Handle, Position, MarkerType, useReactFlow, BaseEdge, EdgeLabelRenderer, getSmoothStepPath } from '@xyflow/react';
import { Link2, UserRound, Component, Server, FileCode2, Maximize } from 'lucide-react';
import { umlProjection } from './uml-model.js';
import { SourceTags } from './SourceTags.jsx';

function UmlNode({ data, selected }) {
  const { node: n, sequence, messages, container, headerHeight=60 } = data;
  const special = ['start', 'end', 'fork', 'join', 'merge'].includes(n.role);
  const icon = n.role === 'actor' ? <UserRound size={35}/> : n.role === 'component' ? <Component size={15}/> : n.role === 'device' ? <Server size={15}/> : n.role === 'artifact' ? <FileCode2 size={15}/> : null;
  return <div role="button" tabIndex={0} aria-label={n.label || n.role} onKeyDown={e=>{if(e.target===e.currentTarget&&(e.key==='Enter'||e.key===' ')){e.preventDefault();e.stopPropagation();data.choose(n);}}} style={{'--uml-header-height':`${headerHeight}px`}} className={`uml-node role-${n.role} ${n.evidence?.length?'has-source':''} ${sequence ? 'is-lifeline' : ''} ${container ? 'is-container' : ''} ${selected ? 'is-selected' : ''}`}>
    {sequence ? messages.flatMap((m, i) => [m.source === n.id && <Handle key={m.id+'out'} id={m.id+'-out'} type="source" position={Position.Right} style={{top:headerHeight+45+i*66,left:'50%',right:'auto'}}/>,
      m.target === n.id && <Handle key={m.id+'in'} id={m.id+'-in'} type="target" position={Position.Left} style={{top:headerHeight+45+i*66,left:'50%',right:'auto'}}/>]) : <>
      <Handle id="top" type="target" position={Position.Top}/><Handle id="bottom" type="source" position={Position.Bottom}/>
      <Handle id="left-out" type="source" position={Position.Left}/><Handle id="right-in" type="target" position={Position.Right}/>
      <Handle id="left" type="target" position={Position.Left}/><Handle id="right" type="source" position={Position.Right}/></>}
    {!special && <div className="uml-node-content">
      {['interface','enum','execution','artifact','component','boundary','control','entity'].includes(n.role) && <small>«{n.role === 'execution' ? 'executionEnvironment' : n.role}»</small>}
      <strong>{icon}{n.label}</strong>
      {!!n.members?.length && <div className="uml-members">{n.members.map((m,i)=><code key={i}>{m}</code>)}</div>}
      <SourceTags refs={n.evidence} mode={data.tagMode} limit={2} onChoose={ref=>data.choose(n,ref)}/>
    </div>}
    {sequence && <div className="uml-lifeline"/>}
  </div>;
}
function UmlEdge(props) {
  const { data, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition } = props;
  let [path, x, y] = getSmoothStepPath({sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, borderRadius:12, ...(data.sequence ? {offset:sourceY===targetY?0:20}: {})});
  if (data.sequence) { path=`M${sourceX},${sourceY} L${targetX},${targetY}`; x=(sourceX+targetX)/2; y=sourceY-13; }
  if (data.sequence && props.source === props.target) { path=`M${sourceX},${sourceY} h55 v28 h-55`; x=sourceX+55; y=sourceY+14; }
  const label = [data.guard ? `[${data.guard}]` : '', ['include','extend','create','destroy'].includes(data.role)?`«${data.role}»`:'', data.label, data.status === 'candidate' ? '候选' : data.status === 'unresolved' ? '未解析' : ''].filter(Boolean).join(' ');
  return <><BaseEdge {...props} path={path} interactionWidth={24}/>{data.role==='destroy'&&<path d={`M${targetX-6},${targetY-6} l12,12 m0,-12 l-12,12`} stroke="#7894b6" strokeWidth="2"/>}{label && <EdgeLabelRenderer><button className={`uml-edge-label nodrag nopan ${props.selected?'is-selected':''}`} style={{transform:`translate(-50%,-50%) translate(${x}px,${y}px)`}} onClick={e=>{e.stopPropagation();data.choose(data);}} title={data.explanation || '查看关系源码依据'}>{label}</button></EdgeLabelRenderer>}</>;
}
const nodeTypes = { uml: UmlNode }, edgeTypes = { uml: UmlEdge };
function Canvas({ model, state, onState, onSelect, externalSelection, tagMode='folded' }) {
  const flow = useReactFlow(), host = useRef(null), ready = useRef(false), callbacks = useRef({onState,onSelect,state});
  callbacks.current = {onState,onSelect,state,selection:externalSelection||state?.selection};
  const anchor=useRef(null);
  const [projection, setProjection] = useState(null), [error,setError] = useState(''), [retry,setRetry] = useState(0);
  useEffect(()=> { let cancelled=false;
    const chosen=[...(host.current?.querySelectorAll('.react-flow__node')||[])].find(el=>el.dataset.id===callbacks.current.selection?.id);
    if(chosen){const shape=model.type==='sequence'?chosen.querySelector('.uml-node-content'):chosen,box=shape.getBoundingClientRect(),frame=host.current.getBoundingClientRect();
      const transform=host.current.querySelector('.react-flow__viewport'),matrix=transform?new DOMMatrix(getComputedStyle(transform).transform):null;
      anchor.current={id:chosen.dataset.id,x:box.left-frame.left+box.width/2,y:box.top-frame.top+box.height/2,viewport:matrix?{x:matrix.e,y:matrix.f,zoom:matrix.a}:flow.getViewport()};}
    ready.current=false; setProjection(null); setError('');
    umlProjection(model,tagMode).then(p=>{if(!cancelled)setProjection(p);}).catch(e=>{if(!cancelled)setError(e.message);});
    return ()=>{cancelled=true;};
  },[model,retry,tagMode]);
  useEffect(()=>{
    if(!projection)return;
    const timer=setTimeout(()=>{ const point=anchor.current,node=point&&projection.nodes.find(n=>n.id===point.id);anchor.current=null;
      if(node){let p={...node.position},parent=node.parentId;while(parent){const n=projection.nodes.find(x=>x.id===parent);p.x+=n.position.x;p.y+=n.position.y;parent=n.parentId;}const next={...point.viewport,x:point.x-(p.x+node.width/2)*point.viewport.zoom,y:point.y-(p.y+(node.data.headerHeight||node.height)/2)*point.viewport.zoom};flow.setViewport(next);callbacks.current.onState({viewport:next});}
      else if(callbacks.current.state?.viewport)flow.setViewport(callbacks.current.state.viewport);else {
      const bounds=flow.getNodesBounds(projection.nodes), width=host.current.clientWidth, height=host.current.clientHeight;
      const zoom=Math.max(.8,Math.min(1,(width-60)/Math.max(bounds.width,1),(height-60)/Math.max(bounds.height,1)));
      flow.setViewport({x:Math.max(30,(width-bounds.width*zoom)/2)-bounds.x*zoom,y:Math.max(30,(height-bounds.height*zoom)/2)-bounds.y*zoom,zoom});
    }ready.current=true; },80);
    return ()=>clearTimeout(timer);
  },[projection,flow]);
  useEffect(()=>{
    if(!projection||!host.current)return;
    let previous={width:host.current.clientWidth,height:host.current.clientHeight};
    const observer=new ResizeObserver(([entry])=>{
      const {width,height}=entry.contentRect;
      if(ready.current&&(width!==previous.width||height!==previous.height)){
        const viewport=flow.getViewport();
        const next={...viewport,x:viewport.x+(width-previous.width)/2,y:viewport.y+(height-previous.height)/2};
        const selectedNode=projection.nodes.find(n=>n.id===callbacks.current.selection?.id);
        if(selectedNode){
          let x=selectedNode.position.x,y=selectedNode.position.y,parent=selectedNode.parentId;
          while(parent){const n=projection.nodes.find(n=>n.id===parent);if(!n)break;x+=n.position.x;y+=n.position.y;parent=n.parentId;}
          const centerX=x+selectedNode.width/2,centerY=y+(model.type==='sequence'?30:selectedNode.height/2);
          if(centerX*next.zoom+next.x<35||centerX*next.zoom+next.x>width-35)next.x=width/2-centerX*next.zoom;
          if(centerY*next.zoom+next.y<35||centerY*next.zoom+next.y>height-35)next.y=height/2-centerY*next.zoom;
        }
        flow.setViewport(next);callbacks.current.onState({viewport:next});
      }
      previous={width,height};
    });
    observer.observe(host.current);return()=>observer.disconnect();
  },[projection,flow,model.type]);
  const select = (element,ref) => callbacks.current.onSelect(element,ref);
  const selected = externalSelection || state?.selection;
  const nodes = useMemo(()=> (projection?.nodes||[]).map(n=>({...n,selected:selected?.id===n.id,draggable:false, data:{...n.data,choose:select,tagMode}})),[projection,selected,tagMode]);
  const edges = useMemo(()=> (projection?.edges||[]).map(e=>{
    const uncertain=['candidate','unresolved'].includes(e.status), isSelected=selected?.id===e.id;
    const color=isSelected?'#245cff':uncertain?'#b17b26':'#7894b6';
    const diamond=['composition','aggregation'].includes(e.role);
    return {...e,type:'uml',selected:isSelected,
      ariaLabel:`关系：${model.nodes.find(n=>n.id===e.source)?.label||e.source} → ${model.nodes.find(n=>n.id===e.target)?.label||e.target}`,
      domAttributes:{onKeyDown:event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();event.stopPropagation();select(e);}}},
      sourceHandle:e.sourceHandle || (['activity','state'].includes(model.type)?'bottom':'right'), targetHandle:e.targetHandle || (['activity','state'].includes(model.type)?'top':'left'),
      data:{...e,sequence:model.type==='sequence',choose:select},
      style:{stroke:color,strokeWidth:isSelected?2.4:1.6,strokeDasharray:uncertain||['return','create','dependency','implementation','include','extend'].includes(e.role)?'6 4':undefined},
      markerEnd:diamond||['association','communication'].includes(e.role)?undefined:['inheritance','implementation'].includes(e.role)?'uml-generalization':{type:['return','async','create','dependency','include','extend'].includes(e.role)?MarkerType.Arrow:MarkerType.ArrowClosed,color,width:18,height:18},
      markerStart:diamond?`uml-${e.role}`:undefined,
    };
  }),[projection,selected,model.type]);
  return <div className="uml-flow" ref={host}>
    <svg className="uml-marker-defs" aria-hidden="true"><defs><marker id="uml-generalization" markerWidth="18" markerHeight="16" refX="16" refY="8" orient="auto"><path d="M1 1 L16 8 L1 15 Z" fill="white" stroke="#7894b6"/></marker>{['composition','aggregation'].map(role=><marker key={role} id={'uml-'+role} markerWidth="18" markerHeight="12" refX="1" refY="6" orient="auto-start-reverse"><path d="M 1 6 L 8 1 L 15 6 L 8 11 Z" stroke="#7894b6" fill={role==='composition'?'#7894b6':'white'}/></marker>)}</defs></svg>
    {error?<div className="uml-empty" role="alert">布局失败：{error}<button onClick={()=>setRetry(n=>n+1)}>重试布局</button></div>:!projection?<div className="uml-empty">正在布局 UML…</div>:
    <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} nodesConnectable={false} nodesDraggable={false} deleteKeyCode={null} minZoom={.12} maxZoom={2.5} fitView={false} zoomOnDoubleClick={false}
      onNodeClick={(_,n)=>select(n.data.node)} onEdgeClick={(_,e)=>select(e.data)}
      onMoveEnd={(_,viewport)=>{if(ready.current)callbacks.current.onState({viewport});}}
      proOptions={{hideAttribution:true}}>
      <Background gap={22} size={.7} color="#dbe5f0"/>
      <Controls showFitView={false} showInteractive={false}><ControlButton title="适应 UML" aria-label="适应 UML" onClick={()=>flow.fitView({padding:.18,maxZoom:1})}><Maximize size={15}/></ControlButton></Controls>
    </ReactFlow>}
  </div>;
}
export function UmlGraph(props) {return <ReactFlowProvider><Canvas {...props}/></ReactFlowProvider>;}
