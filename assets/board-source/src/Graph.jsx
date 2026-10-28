import React, { useEffect, useMemo, useRef, useState } from "react";
import { ReactFlow, Background, Handle, Position, BaseEdge, EdgeLabelRenderer, getSmoothStepPath, useReactFlow, MarkerType } from "@xyflow/react";
import { Boxes, FilePenLine, BookOpen, ShieldCheck, FolderUp, Maximize, ArrowLeft, RotateCcw } from "lucide-react";
import { rankedLayout, focusLayout, layoutViewport } from "./relation-layout.js";
import "./readable-graph.css";
const icons = { save: FilePenLine, read: BookOpen, access: ShieldCheck, assets: FolderUp };
function ModuleNode({ data }) {
  if (data.header) return <div className="reader-lane"><strong>{data.title}</strong></div>;
  if (data.empty) return <div className="reader-empty">{data.title}</div>;
  const Icon = icons[data.object.id] || Boxes;
  return <><Handle id="left-target" type="target" position={Position.Left} isConnectable={false} /><Handle id="right-source" type="source" position={Position.Right} isConnectable={false} />
 <Handle id="top-target" type="target" position={Position.Top} isConnectable={false} /><Handle id="bottom-source" type="source" position={Position.Bottom} isConnectable={false} />
 <button className={`architecture-module nodrag nopan ${data.active ? "is-active" : ""} ${data.focus ? "is-focus" : ""}`} onClick={() => data.onSelect(data.object.id)} onDoubleClick={(e) => {
    e.stopPropagation();
    data.onEnter?.({ kind: "group", id: data.object.id });
  }} title={data.object.title} aria-label={`模块 ${data.object.title}`} aria-pressed={data.active}><div><Icon size={18} /><strong>{data.object.title}</strong></div><span>{data.object.files.length} 个文件{data.cyclic && <em><RotateCcw size={11} />循环引用</em>}</span></button></>;
}
function ModuleEdge(props) {
  const [path, x, y] = getSmoothStepPath({ ...props, borderRadius: 12, offset: 22 });
  return <><BaseEdge path={path} id={props.id} markerEnd={props.markerEnd} style={props.style} interactionWidth={20} />{props.label && <EdgeLabelRenderer><button className="reader-edge-label nodrag nopan" style={{ transform: `translate(-50%,-50%) translate(${x}px,${y}px)` }} onClick={() => props.data.onSelect({ kind: "edge", id: props.data.originalId })}>{props.label}</button></EdgeLabelRenderer>}</>;
}
const nodeTypes = { module: ModuleNode }, edgeTypes = { module: ModuleEdge };
function ArchitectureGraph({ data, selection, info, onSelect, onEnter, heading, actions, navigation }) {
  const flow = useReactFlow(), host = useRef(null), [focus, setFocus] = useState(null), [showIsolated, setShowIsolated] = useState(false), initialized = useRef(false), snapshot = useRef(data.snapshot.id), project = useRef(data.project.root);
  const [canvasWidth, setCanvasWidth] = useState(0), previousWidth = useRef(0);
  useEffect(() => {
    const observer = new ResizeObserver(entries => setCanvasWidth(entries[0].contentRect.width));
    observer.observe(host.current);
    return () => observer.disconnect();
  }, []);
  const groups = useMemo(() => data.groups.map((g) => ({ ...g, name: g.title, kind: "group" })), [data]);
  const projection = useMemo(() => focus ? focusLayout(groups, data.edges.map((e) => ({ ...e, kind: "imports" })), focus, { upstream: "引用此模块", focusTitle: "当前模块", downstream: "此模块引用", showUnknown: true, width: 210, height: 80 }) : rankedLayout(groups, data.edges, { width: 210, height: 80, gapX: 98, gapY: 42, showIsolated }), [groups, data.edges, focus, showIsolated]);
  const active = new Set(info.groups.map((g) => g.id));
  function select(id) {
    setFocus(id);
    onSelect({ kind: "group", id });
  }
  const nodes = [...projection.nodes.map((n) => ({ id: n.id, type: "module", position: { x: n.x, y: n.y }, width: n.width, height: n.height, handles: [
    { id: "left-target", type: "target", position: Position.Left, x: 0, y: n.height / 2 },
    { id: "right-source", type: "source", position: Position.Right, x: n.width, y: n.height / 2 },
    { id: "top-target", type: "target", position: Position.Top, x: n.width / 2, y: 0 },
    { id: "bottom-source", type: "source", position: Position.Bottom, x: n.width / 2, y: n.height }
  ], style: { width: n.width, height: n.height }, data: { object: n.object, title: n.object.name, empty: n.object.kind === "empty", active: active.has(n.object.id), focus: n.role === "focus", cyclic: n.cyclic || n.mutual, onSelect: select, onEnter } })), ...(projection.headers || []).map((h) => ({ id: h.id, type: "module", position: { x: h.x, y: h.y }, width: h.width, height: 36, style: { width: h.width, height: 36 }, selectable: false, focusable: false, data: { header: true, title: h.name } }))];
  const positions = new Map(projection.nodes.map((n) => [n.id, n]));
  const edges = projection.edges.map((e) => {
    const a = positions.get(e.source), b = positions.get(e.target), same = a?.x === b?.x, selected = selection?.kind === "edge" ? selection.id === e.id : active.has(e.source) || active.has(e.target), color = selected ? "#2563eb" : e.cycle ? "#b88836" : "#8da2bb";
    return { ...e, type: "module", sourceHandle: same ? "bottom-source" : "right-source", targetHandle: same ? "top-target" : "left-target", label: selection?.kind === "edge" && selection.id === e.id ? `${e.evidence?.length || 0} 处引用` : e.cycle ? "循环" : "", markerEnd: { type: MarkerType.ArrowClosed, width: 17, height: 17, color }, style: { stroke: color, strokeWidth: selected ? 1.8 : 1.35 }, data: { originalId: e.id, onSelect } };
  });
  useEffect(() => {
    if (project.current !== data.project.root) {
      project.current = data.project.root;
      const degrees = /* @__PURE__ */ new Map();
      for (const e of data.edges) {
        degrees.set(e.source, (degrees.get(e.source) || 0) + 1);
        degrees.set(e.target, (degrees.get(e.target) || 0) + 1);
      }
      const primary = [...groups].sort((a, b) => (degrees.get(b.id) || 0) - (degrees.get(a.id) || 0))[0];
      setFocus(groups.length > 8 ? primary?.id || null : null);
      initialized.current = false;
    }
    if (snapshot.current !== data.snapshot.id) {
      snapshot.current = data.snapshot.id;
      if (focus && !groups.some((g) => g.id === focus)) setFocus(null);
    }
  }, [data, groups, focus]);
  useEffect(() => {
    if (selection?.kind === "file" && info.groups[0]) setFocus(info.groups[0].id);
  }, [selection?.kind, selection?.id]);
  const previousFocus = useRef(focus);
  useEffect(() => {
    const timer = setTimeout(() => {
      if (!initialized.current || previousFocus.current !== focus || previousWidth.current !== canvasWidth) {
        if (focus) {
          const width = host.current?.clientWidth || 900, zoom = Math.min(1, Math.max(0.2, (width - 48) / 798));
          flow.setViewport({ x: width / 2 - (210 + 84 + 105) * zoom, y: 28, zoom });
        } else {
          const width = host.current?.clientWidth || 900, roots = projection.nodes.filter((n) => !n.isolated), bounds = roots.length ? roots : projection.nodes;
          const maxX = Math.max(...bounds.map((n) => n.x + n.width), 210), zoom = Math.max(0.2, Math.min(1, (width - 64) / maxX));
          flow.setViewport({ x: 28, y: 28, zoom });
        }
        initialized.current = true;
        previousFocus.current = focus;
        previousWidth.current = canvasWidth;
      }
    }, 80);
    return () => clearTimeout(timer);
  }, [projection, flow, focus, canvasWidth]);
  function keyboard(e) {
    if (e.target !== e.currentTarget) return;
    const shifts = { ArrowLeft: [70, 0], ArrowRight: [-70, 0], ArrowUp: [0, 70], ArrowDown: [0, -70] };
    if (shifts[e.key]) {
      e.preventDefault();
      const v = flow.getViewport();
      flow.setViewport({ ...v, x: v.x + shifts[e.key][0], y: v.y + shifts[e.key][1] });
    }
  }
  return <>
  <div className="panel-header architecture-toolbar workspace-canvas-toolbar">
    {navigation}
    {heading}
    <div className="architecture-reading-guide"><span>{focus ? "引用方 → 当前模块 → 被引用方" : "从左到右：引用方 → 被引用方"}</span><small>{data.groups.some((g) => g.origin === "directory") ? "目录映射 · 点击模块查看上下游" : "架构映射 · 点击模块查看上下游"}</small></div>
    <div className="panel-actions architecture-toolbar-actions">{focus ? <button className="text-button" onClick={() => setFocus(null)}><ArrowLeft size={12} />全项目概览</button> : projection.isolatedCount > 0 && <button className="text-button" onClick={() => setShowIsolated(!showIsolated)}>{showIsolated ? "收起" : "展开"}无关联模块（{projection.isolatedCount}）</button>}{actions}</div>
  </div>
  <div className="graph-container readable-graph" ref={host} tabIndex={0} role="application" aria-label="模块依赖画布" onKeyDown={keyboard}>
  <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} onEdgeClick={(_, e) => onSelect({ kind: "edge", id: e.data.originalId })} nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} zoomOnDoubleClick={false} minZoom={0.2} maxZoom={1.6} proOptions={{ hideAttribution: true }}><Background color="#dce4ee" gap={22} size={0.7} /></ReactFlow>
  <button className="icon-button code-fit" aria-label="适应视图" title="适应视图" onClick={() => flow.setViewport(layoutViewport(projection, host.current.clientWidth, host.current.clientHeight), { duration: 160 })}><Maximize size={16} /></button>
 </div></>;
}
export {
  ArchitectureGraph
};
