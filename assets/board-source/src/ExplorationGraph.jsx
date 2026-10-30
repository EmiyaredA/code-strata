import React, { useCallback, useEffect, useMemo, useRef } from "react";
import { ReactFlow, Background, Controls, ControlButton, Handle, Position, MarkerType, useReactFlow, BaseEdge, EdgeLabelRenderer, getSmoothStepPath, getBezierPath } from "@xyflow/react";
import { FileCode2, GitBranch, Code2, Maximize } from "lucide-react";
import { rankedLayout, layoutViewport } from "./relation-layout.js";

function ReadingNode({ data }) {
  const node = data.node, unresolved = node.kind === "call" && !node.targetId;
  return <div className={`explore-node ${unresolved ? "is-unresolved" : ""}`}>
    <Handle id="in" type="target" position={Position.Left} />
    <button className="nodrag nopan" onClick={() => data.onSource(node)} title={`${node.name}\n${node.path}:${node.range?.start[0]}`}>
      <strong>{node.kind === "file" ? <FileCode2 size={15}/> : node.kind === "statement" ? <GitBranch size={15}/> : <Code2 size={15}/>}<span>{node.name}</span></strong>
      <small>{unresolved ? "未解析调用点" : node.kind === "statement" ? `${node.nodeType} · 结构语句` : node.kind === "file" ? "文件依赖" : "源码函数"}</small>
      <code>{node.path?.split("/").at(-1)}:{node.range?.start[0]}</code>
    </button>
    <Handle id="out" type="source" position={Position.Right} />
  </div>;
}
function ReadingGroup({ data }) {
  return <div className="explore-group-title"><span>{data.index + 1}</span>{data.title}<small>阅读分组</small></div>;
}
const nodeTypes = { reading: ReadingNode, readingGroup: ReadingGroup };

function ReadingEdge(props) {
  const [path, x, y] = props.source === props.target ? getBezierPath(props) : getSmoothStepPath(props);
  // Labels share a portal above every SVG edge, so another edge cannot paint over them.
  return <><BaseEdge id={props.id} path={path} markerEnd={props.markerEnd} style={props.style} interactionWidth={20}/>
    {props.label && <EdgeLabelRenderer><button className="reader-edge-label explore-edge-label nodrag nopan"
      style={{transform:`translate(-50%,-50%) translate(${x}px,${y}px)`,color:props.style?.stroke}}
      aria-label={`${props.label}：查看源码依据`} onClick={event=>{event.stopPropagation();props.data.onSource(props.data.relation);}}>{props.label}</button></EdgeLabelRenderer>}
  </>;
}
const edgeTypes = { reading: ReadingEdge };

function FitReadingGraph({ host, projection }) {
  const flow = useReactFlow();
  const fit = useCallback(() => {
    const rect = host.current?.getBoundingClientRect();
    if (!rect?.width || !rect.height) return;
    const byId = new Map(projection.map(n => [n.id, n]));
    const nodes = projection.map(n => {
      const parent = byId.get(n.parentId);
      return { x:n.position.x+(parent?.position.x||0), y:n.position.y+(parent?.position.y||0), width:n.style.width, height:n.style.height };
    });
    flow.setViewport(layoutViewport({nodes}, rect.width, rect.height), {duration:0});
  }, [flow, host, projection]);
  useEffect(() => {
    let timer;
    const schedule = () => { clearTimeout(timer); timer = setTimeout(fit, 80); };
    const observer = new ResizeObserver(schedule);
    if (host.current) observer.observe(host.current);
    schedule();
    return () => { observer.disconnect(); clearTimeout(timer); };
  }, [host, fit]);
  return <Controls showInteractive={false} showFitView={false}><ControlButton title="适应阅读图" aria-label="适应阅读图" onClick={fit}><Maximize size={16}/></ControlButton></Controls>;
}

export function readingProjection(view) {
  if (!view.groups?.length) {
    const layout = rankedLayout(view.nodes, view.relations, { width: 230, height: 106, gapX: 100, gapY: 40, showIsolated: true });
    return layout.nodes.map(n => ({ id: n.id, type: "reading", position: { x: n.x, y: n.y }, data: { node: n.object }, style: { width: 230, height: 106 } }));
  }
  const byId = new Map(view.nodes.map(n => [n.id, n])), grouped = new Set(view.groups.flatMap(g => g.nodeIds));
  const rest = view.nodes.filter(n => !grouped.has(n.id));
  const groups = [...view.groups, ...(rest.length ? [{ id: "group:rest", title: "其他关联代码", nodeIds: rest.map(n => n.id) }] : [])];
  return groups.flatMap((group, index) => [
    { id: group.id, type: "readingGroup", position: { x: index * 330, y: 0 }, data: { title: group.title, index },
      style: { width: 276, height: 76 + group.nodeIds.length * 132, background: "#f6f8fc", border: "1px solid #dbe4ef", borderRadius: 14 } },
    ...group.nodeIds.map((id, i) => ({ id, parentId: group.id, extent: "parent", type: "reading", position: { x: 22, y: 64 + i * 132 },
      data: { node: byId.get(id) }, style: { width: 230, height: 106 } })),
  ]);
}

export function ExplorationGraph({ view, onSource }) {
  const host = useRef(null);
  const projection = useMemo(() => readingProjection(view), [view.runId]);
  const nodes = useMemo(() => projection.map(n => ({ ...n, draggable: false, zIndex: n.type === "reading" ? 3 : 0,
    width: n.style.width, height: n.style.height,
    handles: n.type === "reading" ? [
      {id:"in",type:"target",position:Position.Left,x:0,y:n.style.height/2},
      {id:"out",type:"source",position:Position.Right,x:n.style.width,y:n.style.height/2},
    ] : [], data: { ...n.data, onSource } })), [projection, onSource]);
  const openRelation = useCallback(relation => {
    const site = relation.sites?.[0];
    const node = view.nodes.find(n => n.id === relation.target) || view.nodes.find(n => n.id === relation.source);
    onSource({ kind: "source", path: site?.path || relation.path || node?.path, range: site?.range || relation.range || node?.range });
  }, [view, onSource]);
  const edges = useMemo(() => view.relations.map(r => {
    const uncertain = r.status === "candidate" || r.status === "unresolved" || r.kind === "unresolved-call";
    const color = uncertain ? "#bd8730" : "#6285c9";
    const label = r.kind === "calls" ? r.status === "candidate" ? "候选调用" : r.source === r.target ? "递归调用" : "静态调用" :
      r.kind === "unresolved-call" ? "目标未解析" : r.kind === "imports" ? "导入" : r.kind === "structure-contains" ? "包含结构" : "源码顺序";
    return { id: r.id, source: r.source, target: r.target, sourceHandle:"out",targetHandle:"in",type:"reading", zIndex:1, label,
      style: { stroke: color, strokeWidth: 1.7, strokeDasharray: uncertain ? "6 4" : undefined },
      markerEnd: { type: MarkerType.ArrowClosed, color }, data: {relation:r,onSource:openRelation} };
  }), [view, openRelation]);
  // Keep group backgrounds (0), edges (1), label portal (2), and cards (3) independent.
  // Automatic parent-edge elevation would otherwise lift edges above their labels again.
  return <div className="reading-flow" ref={host}><ReactFlow key={view.runId} nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} zIndexMode="manual" nodesConnectable={false} nodesDraggable={false}
    fitView fitViewOptions={{ padding: .18, maxZoom: 1 }} minZoom={.15} maxZoom={1.7} zoomOnDoubleClick={false}
    onEdgeClick={(_, edge) => openRelation(edge.data.relation)} proOptions={{ hideAttribution: true }}>
    <FitReadingGraph host={host} projection={projection}/><Background color="#d9e2ef" gap={22} size={.8}/>
  </ReactFlow></div>;
}
