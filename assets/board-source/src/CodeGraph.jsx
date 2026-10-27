import React, { useEffect, useMemo, useRef, useState } from "react";
import { ReactFlow, Background, Handle, Position, MarkerType, useReactFlow } from "@xyflow/react";
let elkPromise;
const getElk = () => elkPromise ||= import("elkjs/lib/elk.bundled.js").then((m) => new m.default());
import { FileCode2, Braces, Variable, GitBranch, Maximize, ArrowRight } from "lucide-react";
import { kindNames } from "./code-model.js";
function CodeNode({ data }) {
  const n = data.object, Icon = n.kind === "file" ? FileCode2 : n.kind === "statement" ? GitBranch : n.kind === "variable" || n.kind === "parameter" ? Variable : Braces;
  return <>
    <Handle type="target" position={data.vertical ? Position.Top : Position.Left} isConnectable={false} />
    <div className={`code-node ${data.group ? "is-container" : ""} ${data.active ? "is-active" : ""} ${data.related ? "is-related" : ""} ${n.status === "unresolved" ? "is-unresolved" : ""}`} style={data.group ? { height: "100%" } : void 0}>
      <button className="code-node-title nodrag nopan" title={`${n.name}
${n.path}:${n.range.start[0]}`} onClick={() => data.onSelect(n)} onDoubleClick={(e) => {
    e.stopPropagation();
    data.onEnter(n);
  }}>
        <Icon size={16} /><span>{n.kind === "file" ? n.path.split("/").at(-1) : n.name}</span>
      </button>
      <div className="code-node-meta"><span>{n.branch && n.branch !== "body" ? n.branch : kindNames[n.kind] || n.kind}{n.folded ? " · 已折叠" : ""}</span><span>{n.status === "candidate" ? "候选" : n.status === "unresolved" ? "未解析" : n.status === "unsupported" ? "未支持" : `L${n.range.start[0]}`}</span></div>
      {!data.group && n.kind === "file" && <div className="code-node-path" title={n.path}>{n.path}</div>}
      {["file", "class", "function", "method", "lambda", "constructor"].includes(n.kind) && <button className="code-node-enter nodrag nopan" onClick={() => data.onEnter(n)} aria-label={`进入 ${n.name}`}>进入 <ArrowRight size={12} /></button>}
    </div>
    <Handle type="source" position={data.vertical ? Position.Bottom : Position.Right} isConnectable={false} />
  </>;
}
const nodeTypes = { code: CodeNode };
const edgeNames = { imports: "导入", calls: "静态调用", "unresolved-call": "未解析调用", "structure-next": "结构顺序", references: "符号引用" };
function CodeGraph({ result, selection, related, onSelect, onEnter, frame, onViewport, selectedVariable }) {
  const flow = useReactFlow(), [layout, setLayout] = useState(null), [layoutError, setLayoutError] = useState("");
  const restored = useRef(false), refs = useRef({ onSelect, onEnter, onViewport });
  refs.current = { onSelect, onEnter, onViewport };
  const input = useMemo(() => {
    const objects = [...result?.nodes || []].filter((n) => !selectedVariable || related.has(n.id)).slice(0, selectedVariable ? 99 : 100);
    const relations = selectedVariable ? [] : [...result?.relations || []];
    if (selectedVariable) {
      objects.push(selectedVariable);
      for (const id of related || []) if (id !== selectedVariable.id) relations.push({ id: `variable:${id}`, kind: "references", source: selectedVariable.id, target: id });
    }
    return { objects, relations };
  }, [result, selectedVariable, related]);
  useEffect(() => {
    let cancelled = false;
    const ids2 = new Set(input.objects.map((n) => n.id)), children = /* @__PURE__ */ new Map();
    for (const n of input.objects) {
      const parent = !selectedVariable && frame.view !== "files" && ids2.has(n.ownerId) ? n.ownerId : "root";
      if (!children.has(parent)) children.set(parent, []);
      children.get(parent).push(n);
    }
    const build = (parent) => (children.get(parent) || []).map((n) => ({ id: n.id, width: n.kind === "statement" ? 280 : 240, height: n.kind === "file" ? 116 : 88, ...children.has(n.id) ? { children: build(n.id), layoutOptions: { "elk.padding": "[top=80,left=22,bottom=22,right=22]", "elk.direction": "DOWN" } } : {} }));
    const graph = { id: "root", layoutOptions: { "elk.algorithm": "layered", "elk.direction": frame.view === "logic" && !selectedVariable ? "DOWN" : "RIGHT", "elk.spacing.nodeNode": "44", "elk.layered.spacing.nodeNodeBetweenLayers": "90", "elk.hierarchyHandling": "INCLUDE_CHILDREN", "elk.edgeRouting": "ORTHOGONAL" }, children: build("root"), edges: input.relations.filter((r) => r.kind !== "contains" && ids2.has(r.source) && ids2.has(r.target)).sort((a, b) => (b.kind === "references") - (a.kind === "references")).slice(0, 300).map((r) => ({ id: r.id, sources: [r.source], targets: [r.target] })) };
    const apply = (root) => {
      if (cancelled) return;
      const positioned = [];
      function walk(ns, parent) {
        for (const n of ns || []) {
          positioned.push({ id: n.id, position: { x: n.x || 0, y: n.y || 0 }, ...parent ? { parentId: parent, extent: "parent" } : {}, width: n.width, height: n.height, style: { width: n.width, height: n.height }, group: !!n.children?.length });
          walk(n.children, n.id);
        }
      }
      walk(root.children);
      setLayout(positioned);
      setLayoutError("");
    };
    if (frame.view === "files" && !graph.edges.length) {
      const width = document.querySelector('.code-graph-wrap')?.clientWidth || 800;
      const columns = Math.max(1,Math.min(3,Math.floor(width/300)));
      apply({children:graph.children.map((n,i)=>({...n,x:24+(i%columns)*300,y:24+Math.floor(i/columns)*156}))});
      return ()=>{cancelled=true;};
    }
    getElk().then((elk) => elk.layout(graph)).then(apply).catch(() => {
      if (!cancelled) {
        setLayoutError("自动布局暂不可用，使用列表布局");
        apply({ children: input.objects.map((n, i) => ({ id: n.id, x: 40 + i % 3 * 340, y: 40 + Math.floor(i / 3) * 150, width: 280, height: 110 })) });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [input, frame.view, selectedVariable]);
  useEffect(() => {
    if (!layout?.length) return;
    const timer = setTimeout(() => {
      if (!restored.current && frame.viewport) flow.setViewport(frame.viewport);
      else if (!restored.current) {
        const first = layout.find((n) => !n.parentId);
        if (frame.view === "logic" && first) {
          const width = flow.getViewport ? document.querySelector(".code-graph-wrap")?.clientWidth || 700 : 700;
          flow.setViewport({ x: (width - first.width) / 2 - first.position.x, y: 24 - first.position.y, zoom: 1 });
        } else if (first && layout.length > 6) {
          const roots=layout.filter(n=>!n.parentId), width=document.querySelector('.code-graph-wrap')?.clientWidth||800;
          const left=Math.min(...roots.map(n=>n.position.x)), right=Math.max(...roots.map(n=>n.position.x+n.width));
          const focus=layout.find(n=>n.id===result.focus?.id&&!n.parentId)||first, zoom=.9;
          flow.setViewport({x:Math.max(24,(width-(right-left)*zoom)/2)-left*zoom,y:24-focus.position.y*zoom,zoom});
        } else flow.fitView({ padding: 0.2, minZoom: 0.8, maxZoom: 1 });
      }
      restored.current = true;
    }, 80);
    return () => clearTimeout(timer);
  }, [layout, flow, frame.viewport]);
  const lastVariable = useRef(selectedVariable?.id), beforeVariable = useRef(null);
  useEffect(() => {
    if (!layout?.length) return;
    if (selectedVariable && lastVariable.current !== selectedVariable.id && layout.some((n) => n.id === selectedVariable.id)) {
      if (!lastVariable.current) beforeVariable.current = flow.getViewport();
      lastVariable.current = selectedVariable.id;
      const timer = setTimeout(() => flow.fitView({ padding: 0.15, minZoom: 0.65, maxZoom: 0.9, duration: 120 }), 80);
      return () => clearTimeout(timer);
    }
    if (!selectedVariable && lastVariable.current) {
      lastVariable.current = null;
      if (beforeVariable.current) flow.setViewport(beforeVariable.current);
    }
  }, [layout, selectedVariable, flow]);
  const byId = new Map(input.objects.map((n) => [n.id, n]));
  const nodes = (layout || []).filter(n => byId.has(n.id)).map((n) => ({ ...n, type: "code", data: { object: byId.get(n.id), group: n.group, active: selection?.id === n.id, related: related?.has(n.id), vertical: frame.view === "logic" && !selectedVariable, onSelect: (o) => refs.current.onSelect(o), onEnter: (o) => refs.current.onEnter(o) } }));
  const ids = new Set(nodes.map((n) => n.id));
  const edges = input.relations.filter((r) => r.kind !== "contains" && ids.has(r.source) && ids.has(r.target)).sort((a, b) => (b.kind === "references") - (a.kind === "references")).slice(0, 300).map((r) => ({ id: r.id, source: r.source, target: r.target, type: "smoothstep", label: r.kind === "structure-next" ? "" : r.kind === "calls" && r.status === "candidate" ? "候选调用" : (edgeNames[r.kind] || r.kind) + (r.siteCount > 1 ? ` · ${r.siteCount}` : ""), labelStyle: { fill: "#64748b", fontSize: 11 }, labelBgStyle: { fill: "#f8fafc" }, markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: r.kind === "references" ? "#2563eb" : "#94a3b8" }, style: { stroke: r.kind === "references" ? "#2563eb" : "#b7c5d8", strokeWidth: r.kind === "references" ? 1.8 : 1.2, strokeDasharray: r.kind === "references" || r.status === "candidate" || r.kind === "unresolved-call" ? "5 4" : void 0 }, data: r }));
  return <div className="code-graph-wrap">
    <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} nodesDraggable={false} nodesConnectable={false} minZoom={0.15} maxZoom={1.7} onMoveEnd={(_, v) => refs.current.onViewport(v)} onEdgeClick={(_, e) => onSelect({ ...e.data, kind: "relation" })} onNodeDoubleClick={(_, n) => onEnter(n.data.object)} proOptions={{ hideAttribution: true }}><Background color="#dce4ee" gap={22} size={0.7} /></ReactFlow>
    <button className="icon-button code-fit" aria-label="适应代码画布" title="适应画布" onClick={() => flow.fitView({ padding: 0.2, maxZoom: 1, duration: 180 })}><Maximize size={16} /></button>
    {layoutError && <span className="code-layout-note">{layoutError}</span>}
  </div>;
}
export {
  CodeGraph
};
