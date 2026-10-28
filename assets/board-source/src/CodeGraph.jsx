import React, { useEffect, useMemo, useRef, useState } from "react";
import { ReactFlow, Background, Handle, Position, MarkerType, useReactFlow, BaseEdge, EdgeLabelRenderer, getSmoothStepPath } from "@xyflow/react";
import { FileCode2, Braces, Variable, GitBranch, Maximize, ArrowRight, LogIn, LogOut, TriangleAlert, RotateCcw, ChevronDown } from "lucide-react";
import { kindNames, containsRange, innermost } from "./code-model.js";
import { focusLayout, rankedLayout, layoutViewport } from "./relation-layout.js";
let elkPromise;
const getElk = () => elkPromise ||= import("elkjs/lib/elk.bundled.js").then((m) => new m.default());
function ReaderNode({ data }) {
  const n = data.object, terminal = n.kind === "exit" || /^(Return|Raise|Throw|Break|Continue)/.test(n.nodeType || ""), control = /If|For|While|Switch|Try|With/.test(n.nodeType || "");
  const Icon = n.kind === "file" ? FileCode2 : n.kind === "entry" ? LogIn : terminal ? LogOut : control ? GitBranch : n.kind === "summary" ? TriangleAlert : n.kind === "variable" || n.kind === "parameter" ? Variable : Braces;
  if (n.kind === "lane") return <div className="reader-lane"><strong>{n.name}</strong><span>{n.subtitle}</span></div>;
  if (n.kind === "empty") return <div className="reader-empty">{n.name}</div>;
  const title = n.moduleTopLevel ? "模块顶层代码" : n.kind === "file" ? n.path.split("/").at(-1) : n.kind === "statement" ? n.name : n.name;
  return <>
  <Handle id="in" type="target" position={data.vertical ? Position.Top : Position.Left} isConnectable={false} />
  <div data-node-type={n.nodeType} className={`reader-node ${data.active ? "is-active" : ""} ${data.role === "focus" ? "is-focus" : ""} ${data.related ? "is-related" : ""} ${n.kind === "summary" ? "is-summary" : ""} ${terminal ? "is-terminal" : ""} ${control ? "is-control" : ""} ${n.kind === "entry" ? "is-entry" : ""}`}>
   <button className="reader-node-main nodrag nopan" onClick={() => n.kind === "summary" ? data.onToggleUnknown() : data.onSelect(n)} onDoubleClick={(e) => {
    e.stopPropagation();
    if (!["entry", "summary"].includes(n.kind)) data.onEnter(n);
  }} title={`${title}
${n.path || ""}${n.range ? ":" + n.range.start[0] : ""}`}>
    <div><Icon size={16} /><strong>{title}</strong>{n.kind === "summary" && <ChevronDown size={14} />}</div>
    <small>{n.kind === "summary" ? "展开查看调用位置" : n.kind === "entry" ? "函数体开始" : n.kind === "statement" ? terminal ? "返回 / 中断位置" : control ? "结构分支" : n.branch && n.branch !== "body" ? n.branch : "语句" : `${n.moduleTopLevel ? "调用点" : kindNames[n.kind] || n.kind}${n.asyncFunction ? " · async" : ""}`}</small>
    {data.role === "focus" && n.parameters && <span className="reader-parameters">参数：{n.parameters.join(", ") || "无"}</span>}{n.range && <span className="reader-location">{n.kind === "file" ? n.path : n.path?.split("/").at(-1)}:{n.range.start[0]}</span>}
   </button>
   {["file", "class", "function", "method", "constructor", "lambda"].includes(n.kind) && <button className="reader-enter nodrag nopan" aria-label={n.kind === "file" ? `查看 ${n.path} 的函数` : `${data.role === "focus" ? "查看逻辑" : "聚焦函数"} ${n.name}`} onClick={() => n.moduleTopLevel || n.kind === "class" && data.role === "focus" ? data.onSelect(n) : data.onEnter(n)}>{n.moduleTopLevel ? "看调用点" : n.kind === "file" ? "看函数" : n.kind === "class" && data.role === "focus" ? "看声明" : data.role === "focus" ? "看逻辑" : "聚焦"}<ArrowRight size={12} /></button>}
   {data.mutual && <span className="reader-cycle"><RotateCcw size={11} />互相调用</span>}
  </div>
  <Handle id="out" type="source" position={data.vertical ? Position.Bottom : Position.Right} isConnectable={false} />
  <Handle id="loop-out" type="source" position={Position.Top} style={{ left: "75%" }} isConnectable={false} /><Handle id="loop-in" type="target" position={Position.Top} style={{ left: "25%" }} isConnectable={false} />
 </>;
}
function ReaderEdge(props) {
  const self = props.source === props.target;
  const [path, x, y] = self ? [`M ${props.sourceX} ${props.sourceY} C ${props.sourceX + 90} ${props.sourceY - 100}, ${props.targetX - 90} ${props.targetY - 100}, ${props.targetX} ${props.targetY}`, (props.sourceX + props.targetX) / 2, props.sourceY - 74] : getSmoothStepPath({ ...props, borderRadius: 10, offset: 24 });
  return <><BaseEdge path={path} id={props.id} markerEnd={props.markerEnd} style={props.style} interactionWidth={20} />{props.label && <EdgeLabelRenderer><button className={`reader-edge-label nodrag nopan ${self ? "is-recursive" : ""}`} style={{ transform: `translate(-50%,-50%) translate(${x}px,${y}px)` }} onClick={() => props.data.onSelect({ ...props.data.relation, kind: "relation" })}>{props.label}</button></EdgeLabelRenderer>}</>;
}
const nodeTypes = { reader: ReaderNode }, edgeTypes = { reader: ReaderEdge };
// Fixed-size cards expose their ports explicitly so controlled re-renders retain edge anchors.
function readerHandles(width, height, vertical) {
  return [
    { id: "in", type: "target", position: vertical ? Position.Top : Position.Left, x: vertical ? width / 2 : 0, y: vertical ? 0 : height / 2 },
    { id: "out", type: "source", position: vertical ? Position.Bottom : Position.Right, x: vertical ? width / 2 : width, y: vertical ? height : height / 2 },
    { id: "loop-in", type: "target", position: Position.Top, x: width / 4, y: 0 },
    { id: "loop-out", type: "source", position: Position.Top, x: width * .75, y: 0 }
  ];
}
function logicProjection(result, selectedVariable, related) {
  const objects = result.nodes || [], focus = result.focus, entry = { id: "ui:entry:" + focus.id, kind: "entry", name: focus.name, path: focus.path, range: { start: focus.range.start, end: focus.range.start }, status: "resolved" };
  if (selectedVariable) {
    const statements = objects.filter((n) => related.has(n.id)), def = innermost(objects.filter((n) => n.path === selectedVariable.path), selectedVariable.range);
    const nodes2 = [{ id: selectedVariable.id, object: selectedVariable, x: 0, y: 112, width: 220, height: 96, role: "focus" }, ...statements.map((n, i) => ({ id: n.id, object: n, x: 340, y: 64 + i * 124, width: 280, height: 96 }))];
    return { nodes: nodes2, headers: [{ id: "lane:definition", name: "变量定义", x: 0, y: 0, width: 220 }, { id: "lane:uses", name: "符号引用位置", x: 340, y: 0, width: 280 }], edges: statements.map((n) => ({ id: "ui:reference:" + n.id, source: selectedVariable.id, target: n.id, kind: n.id === def?.id ? "defines" : "references", label: n.id === def?.id ? "定义" : "引用" })) };
  }
  const byId = new Map(objects.map((n) => [n.id, n])), children = /* @__PURE__ */ new Map();
  for (const n of objects) {
    const owner = byId.has(n.ownerId) ? n.ownerId : "root";
    if (!children.has(owner)) children.set(owner, []);
    children.get(owner).push(n);
  }
  const edges = (result.relations || []).filter((r) => r.kind === "structure-next").map((r) => ({ ...r, label: "" }));
  const roots = children.get("root") || [];
  if (roots[0]) edges.push({ id: "ui:start", source: entry.id, target: roots[0].id, kind: "structure-next", label: "进入函数体" });
  for (const [parent, items] of children) {
    if (parent === "root") continue;
    const firstByBranch = /* @__PURE__ */ new Map();
    for (const n of items) if (!firstByBranch.has(n.branch)) firstByBranch.set(n.branch, n);
    for (const [branch, n] of firstByBranch) {
      const parentType = byId.get(parent)?.nodeType || "";
      const label = branch === "主体" && /If/.test(parentType) ? "条件成立" : branch === "否则 / 正常结束" && /If/.test(parentType) ? "条件不成立" : branch === "主体" && /For|While/.test(parentType) ? "循环主体" : branch === "主体" && /Try/.test(parentType) ? "try 主体" : branch || "包含结构";
      edges.push({ id: "ui:branch:" + n.id, source: parent, target: n.id, kind: "structure-branch", label });
    }
  }
  const all = [entry, ...objects];
  if (!roots.length) {
    const end = { id: "ui:end:" + focus.id, kind: "exit", name: "函数体末尾", path: focus.path, range: { start: focus.range.end, end: focus.range.end }, status: "resolved" };
    all.push(end);
    edges.push({ id: "ui:empty-body", source: entry.id, target: end.id, kind: "structure-next", label: "空函数体" });
  }
  const layout = rankedLayout(all, edges, { width: 92, height: 280, gapX: 48, gapY: 44, showIsolated: true });
  const nodes = layout.nodes.map((n) => ({ ...n, x: n.y - 66, y: n.x + 70, width: 280, height: 92 }));
  nodes.unshift();
  return { nodes, edges, headers: [], vertical: true };
}
function CodeGraph({ result, selection, related, onSelect, onEnter, frame, onViewport, selectedVariable, onStats }) {
  const flow = useReactFlow(), host = useRef(null), restored = useRef(false), [showUnknown, setShowUnknown] = useState(frame.showUnknown || false);
  const callbacks = useRef({ onSelect, onEnter, onViewport });
  callbacks.current = { onSelect, onEnter, onViewport };
  const baseProjection = useMemo(() => {
    if (frame.view === "logic") return logicProjection(result, selectedVariable, related);
    if (frame.view === "references") {
      const focus = result.focus, uses = result.nodes.filter((n) => n.id !== focus.id);
      return { nodes: [{ id: focus.id, object: focus, x: 0, y: 66, width: 220, height: 96, role: "focus" }, ...uses.map((n, i) => ({ id: n.id, object: n, x: 340, y: 66 + i * 120, width: 280, height: 96 }))], headers: [{ id: "lane:def", name: "变量定义", x: 0, y: 0, width: 220 }, { id: "lane:refs", name: "引用位置", x: 340, y: 0, width: 280 }], edges: uses.map((n) => ({ id: "ui:use:" + n.id, kind: "references", source: focus.id, target: n.id, label: n.access === "write" ? "赋值" : n.access === "readwrite" ? "读写" : n.access === "type" ? "类型引用" : "读取" })) };
    }
    if ((frame.hops || 1) > 1) {
      const output = rankedLayout(result.nodes.filter((n) => n.kind !== "call" || showUnknown), result.relations.filter((r) => r.kind !== "contains"), { showIsolated: true, width: 216, height: 92, gapX: 92, gapY: 32 });
      if (frame.view === "functions") output.headers = output.headers.map((h, i) => ({ ...h, name: h.id === "lane:isolated" ? "无已解析调用关系" : i === 0 ? "本范围调用起点" : `调用第 ${i} 层` }));
      return output;
    }
    const file = frame.view === "files";
    const objects = result.nodes.map((n) => n.id === result.focus?.id ? { ...n, parameters: ["function", "method", "constructor", "lambda"].includes(n.kind) ? (result.variables || []).filter((v) => v.kind === "parameter" && v.ownerId === n.id).sort((a, b) => a.range.start[0] - b.range.start[0] || a.range.start[1] - b.range.start[1]).map((v) => v.name) : void 0 } : n);
    return focusLayout(objects, result.relations, result.focus?.id, { upstream: file ? "引用此文件" : "调用此函数", focusTitle: file ? "当前文件" : "当前函数", downstream: file ? "此文件引用" : "此函数调用", showUnknown });
  }, [result, frame.view, frame.hops, showUnknown, selectedVariable, related]);
  const [logicLayout, setLogicLayout] = useState(null);
  useEffect(() => {
    if (frame.view !== "logic" || selectedVariable) {
      setLogicLayout(null);
      return;
    }
    let cancelled = false;
    const graph = { id: "logic", layoutOptions: { "elk.algorithm": "layered", "elk.direction": "DOWN", "elk.spacing.nodeNode": "64", "elk.layered.spacing.nodeNodeBetweenLayers": "52", "elk.edgeRouting": "ORTHOGONAL" }, children: baseProjection.nodes.map((n) => ({ id: n.id, width: n.width, height: n.height })), edges: baseProjection.edges.map((r) => ({ id: r.id, sources: [r.source], targets: [r.target] })) };
    getElk().then((elk) => elk.layout(graph)).then((placed) => {
      if (!cancelled) {
        const coordinates = new Map(placed.children.map((n) => [n.id, n]));
        setLogicLayout({ input: baseProjection, nodes: baseProjection.nodes.map((n) => ({ ...n, x: coordinates.get(n.id)?.x || 0, y: coordinates.get(n.id)?.y || 0 })) });
      }
    }).catch(() => {
      if (!cancelled) setLogicLayout({ input: baseProjection, nodes: baseProjection.nodes });
    });
    return () => {
      cancelled = true;
    };
  }, [baseProjection, frame.view, selectedVariable]);
  const projection = logicLayout?.input === baseProjection ? { ...baseProjection, nodes: logicLayout.nodes } : baseProjection;
  useEffect(() => {
    onStats?.({ visible: new Set(projection.nodes.filter((n) => !n.id.startsWith("ui:") && !["empty", "summary", "entry"].includes(n.object.kind)).map((n) => n.object.id)).size, unknown: projection.unknownCount || 0 });
  }, [baseProjection, onStats]);
  const byLayout = new Map(projection.nodes.map((n) => [n.id, n]));
  const nodes = [...projection.nodes.map((n) => ({ id: n.id, type: "reader", position: { x: n.x, y: n.y }, width: n.width, height: n.height, handles: readerHandles(n.width, n.height, projection.vertical), style: { width: n.width, height: n.height }, draggable: false, data: { ...n, object: n.object, vertical: projection.vertical, active: selection?.id === n.object.id, related: related?.has(n.object.id), onSelect: (n2) => callbacks.current.onSelect(n2), onEnter: (n2) => callbacks.current.onEnter(n2), onToggleUnknown: () => {
    frame.showUnknown = !showUnknown;
    setShowUnknown(!showUnknown);
  } } })), ...(projection.headers || []).map((h) => ({ id: h.id, type: "reader", position: { x: h.x, y: h.y }, width: h.width, height: 40, style: { width: h.width, height: 40 }, selectable: false, focusable: false, data: { object: { kind: "lane", name: h.name } } }))];
  const edges = projection.edges.filter((r) => byLayout.has(r.source) && byLayout.has(r.target)).slice(0, 300).map((r) => {
    const self = r.source === r.target, uncertain = r.status === "candidate" || r.status === "unresolved", blue = ["references", "defines"].includes(r.kind), color = blue ? "#2563eb" : uncertain ? "#b88836" : "#7891ad";
    return { id: r.id, source: r.source, target: r.target, type: "reader", sourceHandle: self ? "loop-out" : "out", targetHandle: self ? "loop-in" : "in", label: self ? "递归" : r.label || (r.kind === "calls" ? r.status === "candidate" ? "候选" : r.siteCount > 1 ? `${r.siteCount} 处调用` : "" : r.kind === "imports" ? "导入" : ""), markerEnd: { type: MarkerType.ArrowClosed, width: 17, height: 17, color }, style: { stroke: color, strokeWidth: self || blue ? 1.8 : 1.4, strokeDasharray: uncertain || r.kind === "references" ? "5 4" : void 0 }, data: { relation: r, onSelect: (n) => callbacks.current.onSelect(n) } };
  });
  const variableBefore = useRef(null), lastVariable = useRef(selectedVariable?.id);
  useEffect(() => {
    const timer = setTimeout(() => {
      const width = host.current?.clientWidth || 850;
      if (!restored.current) {
        if (frame.viewport) flow.setViewport(frame.viewport);
        else if (frame.view === "references") flow.setViewport({ x: 32, y: 64, zoom: 0.9 });
        else if (frame.view === "logic") {
          if (!selectedVariable && logicLayout?.input !== baseProjection) return;
          const entry = projection.nodes.find((n) => n.object.kind === "entry") || projection.nodes[0];
          flow.setViewport({ x: width / 2 - (entry?.x || 0) - 140, y: 56 - (entry?.y || 0), zoom: 1 });
        } else {
          const focus = projection.nodes.find((n) => n.role === "focus") || projection.nodes[0];
          const zoom = Math.max(0.78, Math.min(1, (width - 48) / 816));
          flow.setViewport({ x: width / 2 - ((focus?.x || 0) + (focus?.width || 216) / 2) * zoom, y: 56, zoom });
        }
        restored.current = true;
      }
      if (selectedVariable?.id !== lastVariable.current) {
        if (selectedVariable) {
          variableBefore.current = flow.getViewport();
          flow.setViewport({x:Math.max(24,(width-620*.9)/2),y:56,zoom:.9},{duration:120});
        } else if (variableBefore.current) flow.setViewport(variableBefore.current);
        lastVariable.current = selectedVariable?.id;
      }
    }, 70);
    return () => clearTimeout(timer);
  }, [baseProjection, logicLayout, flow, frame.view, selectedVariable?.id]);
  return <div className="code-graph-wrap readable-graph" ref={host}>
  <div className="graph-reading-guide">{frame.view === "logic" ? selectedVariable ? "变量定义 → 符号引用" : "函数体开始 → 结构分支 → 返回 / 中断" : frame.view === "files" ? "引用方 → 当前文件 → 被引用方" : frame.view === "references" ? "变量定义 → 引用位置" : "调用方 → 当前函数 → 被调用方"}<small>{frame.view === "logic" ? "结构简图；异常与异步路径不作完整展开" : "箭头表示静态关系"}</small></div>
  <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} nodesDraggable={false} nodesConnectable={false} zoomOnDoubleClick={false} minZoom={0.2} maxZoom={1.6} onMoveEnd={(_, v) => callbacks.current.onViewport(v)} onEdgeClick={(_, e) => callbacks.current.onSelect({ ...e.data.relation, kind: "relation" })} proOptions={{ hideAttribution: true }}><Background color="#dce4ee" gap={22} size={0.7} /></ReactFlow>
  <button className="icon-button code-fit" aria-label="适应代码画布" title="适应画布" onClick={() => flow.setViewport(layoutViewport(projection, host.current.clientWidth, host.current.clientHeight), { duration: 160 })}><Maximize size={16} /></button>
  {showUnknown && projection.unknownCount > 0 && <button className="text-button graph-hide-unknown" onClick={() => {
    frame.showUnknown = false;
    setShowUnknown(false);
  }}>收起未解析调用</button>}
 </div>;
}
export {
  CodeGraph
};
