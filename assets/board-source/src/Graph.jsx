import React, { useEffect, useMemo, useRef } from "react";
import {
  ReactFlow,
  Background,
  Handle,
  Position,
  useReactFlow,
  BaseEdge,
  EdgeLabelRenderer,
  getSmoothStepPath,
} from "@xyflow/react";
import {
  Boxes,
  FilePenLine,
  BookOpen,
  ShieldCheck,
  FolderUp,
  Maximize,
} from "lucide-react";
const icons = {
  save: FilePenLine,
  read: BookOpen,
  access: ShieldCheck,
  assets: FolderUp,
};
function Responsibility({ data }) {
  const Icon = icons[data.id] || Boxes;
  return (
    <>
      <button
        className={`responsibility nodrag nopan ${data.active ? "is-active" : ""} ${data.dim ? "is-dim" : ""}`}
        onClick={() => data.onSelect({ kind: "group", id: data.id })}
        onDoubleClick={() => data.onEnter?.({kind:"group", id:data.id})}
        aria-label={`模块 ${data.title}`}
        aria-pressed={data.active}
        title={data.title}
      >
        <Icon size={18} />
        <span>{data.title}</span>
      </button>
      {[
        ["left", Position.Left],
        ["right", Position.Right],
        ["top", Position.Top],
        ["bottom", Position.Bottom],
      ].flatMap(([id, position]) =>
        ["source", "target"].map((type) => (
          <Handle
            key={`${id}-${type}`}
            id={`${id}-${type}`}
            type={type}
            position={position}
            isConnectable={false}
          />
        )),
      )}
    </>
  );
}
const nodeTypes = { responsibility: Responsibility };
function EvidenceEdge(props) {
  const [path, x, y] = getSmoothStepPath(props);
  return (
    <>
      <BaseEdge
        id={props.id}
        path={path}
        markerEnd={props.markerEnd}
        style={props.style}
        interactionWidth={20}
      />
      <EdgeLabelRenderer>
        <button
          className="edge-label nodrag nopan"
          aria-label={`查看${props.data.ariaLabel || "代码引用"}`}
          style={{
            transform: `translate(-50%, -50%) translate(${x}px, ${y}px)`,
          }}
          onClick={() => props.data.onSelect({ kind: "edge", id: props.id })}
        >
          {props.label}
        </button>
      </EdgeLabelRenderer>
    </>
  );
}
const edgeTypes = { evidence: EvidenceEdge };
export function ArchitectureGraph({ data, selection, info, onSelect, onEnter }) {
  const flow = useReactFlow(),
    host = useRef(null),
    initialized = useRef(false),
    lastSnapshot = useRef(null),
    lastProject = useRef(data.project.root || "demo");
  const positions = useMemo(
    () =>
      new Map(
        data.groups.map((g, i) => [
          g.id,
          {
            x:
              Math.floor(i / Math.max(2, Math.ceil(data.groups.length / 3))) *
                330 +
              40,
            y: (i % Math.max(2, Math.ceil(data.groups.length / 3))) * 150 + 60,
          },
        ]),
      ),
    [data],
  );
  const active = new Set(info.groups.map((g) => g.id));
  const nodes = data.groups.map((g) => ({
    id: g.id,
    type: "responsibility",
    position: positions.get(g.id),
    data: {
      ...g,
      active: active.has(g.id),
      dim: active.size > 0 && !active.has(g.id),
      onSelect,
      onEnter,
    },
    draggable: false,
    focusable: false,
    style: { width: 186, height: 62 },
  }));
  const edges = data.edges.map((e) => {
    const a = positions.get(e.source),
      b = positions.get(e.target),
      vertical = a.x === b.x,
      selected =
        selection?.kind === "edge"
          ? selection.id === e.id
          : active.has(e.source) || active.has(e.target);
    return {
      ...e,
      sourceHandle: vertical
        ? a.y < b.y
          ? "bottom-source"
          : "top-source"
        : "right-source",
      targetHandle: vertical
        ? a.y < b.y
          ? "top-target"
          : "bottom-target"
        : "left-target",
      type: "evidence",
      data: {
        onSelect,
      onEnter,
        ariaLabel: `引用 ${data.groups.find((g) => g.id === e.source)?.title} 到 ${data.groups.find((g) => g.id === e.target)?.title}`,
      },
      label:
        selection?.kind === "edge" && selection.id === e.id
          ? `${e.evidence.length} 处代码引用`
          : "代码引用",
      markerEnd: {
        type: "arrowclosed",
        color: selected ? "#1d4ed8" : "#94a3b8",
        width: 16,
        height: 16,
      },
      style: {
        stroke: selected ? "#1d4ed8" : "#a8b4c5",
        strokeWidth: selected ? 1.6 : 1.2,
        opacity: active.size && !selected ? 0.65 : 1,
      },
      labelStyle: { fontSize: 11, fill: selected ? "#475569" : "#94a3b8" },
      labelBgStyle: { fill: "#fbfcfe", fillOpacity: 0.96 },
      labelBgPadding: [6, 4],
      interactionWidth: 20,
      focusable: true,
      ariaLabel: `引用 ${data.groups.find((g) => g.id === e.source)?.title} 到 ${data.groups.find((g) => g.id === e.target)?.title}`,
    };
  });
  useEffect(() => {
    if (!initialized.current) return;
    if (lastSnapshot.current !== data.snapshot.id) {
      lastSnapshot.current = data.snapshot.id;
      const project = data.project.root || "demo";
      if (lastProject.current !== project) {
        lastProject.current = project;
        requestAnimationFrame(() => flow.fitView({ padding: 0.24, maxZoom: 1, duration: 0 }));
      }
    }
  }, [data.snapshot.id, flow]);
  useEffect(() => {
    if (
      !initialized.current ||
      !["file", "group"].includes(selection?.kind) ||
      !info.groups.length ||
      !host.current
    )
      return;
    const v = flow.getViewport(),
      { width, height } = host.current.getBoundingClientRect(),
      p = positions.get(info.groups[0].id);
    if (!p) return;
    const left = p.x * v.zoom + v.x,
      top = p.y * v.zoom + v.y,
      right = left + 186 * v.zoom,
      bottom = top + 62 * v.zoom,
      pad = 52,
      dx =
        left < pad ? pad - left : right > width - pad ? width - pad - right : 0,
      dy =
        top < pad
          ? pad - top
          : bottom > height - pad
            ? height - pad - bottom
            : 0;
    if (dx || dy)
      flow.setViewport(
        { ...v, x: v.x + dx, y: v.y + dy },
        { duration: 180, interpolate: "linear" },
      );
  }, [selection, info, positions, flow]);
  function keyboard(e) {
    if (e.target !== e.currentTarget) return;
    const shifts = {
      ArrowLeft: [70, 0],
      ArrowRight: [-70, 0],
      ArrowUp: [0, 70],
      ArrowDown: [0, -70],
    };
    if (shifts[e.key]) {
      e.preventDefault();
      const v = flow.getViewport();
      flow.setViewport({
        ...v,
        x: v.x + shifts[e.key][0],
        y: v.y + shifts[e.key][1],
      });
    }
    if (e.key === "+" || e.key === "=") {
      e.preventDefault();
      flow.zoomIn();
    }
    if (e.key === "-") {
      e.preventDefault();
      flow.zoomOut();
    }
  }
  return (
    <div
      className="graph-container"
      ref={host}
      tabIndex={0}
      role="application"
      aria-label="系统架构画布"
      onKeyDown={keyboard}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onEdgeClick={(_, edge) => onSelect({ kind: "edge", id: edge.id })}
        onInit={() => {
          initialized.current = true;
          lastSnapshot.current = data.snapshot.id;
          requestAnimationFrame(() =>
            flow.fitView({ padding: 0.24, maxZoom: 1 }),
          );
        }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnDrag
        minZoom={0.2}
        maxZoom={1.5}
        zoomOnDoubleClick={false}
        preventScrolling
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#dbe3ef" gap={24} size={0.7} />
      </ReactFlow>
      {data.groups.every((g) => g.origin === "directory") && (
        <div className="canvas-caption">目录映射</div>
      )}
      <button
        className="fit-button icon-button"
        title="适应视图"
        aria-label="适应视图"
        onClick={() =>
          flow.fitView({ padding: 0.24, maxZoom: 1, duration: 180 })
        }
      >
        <Maximize size={16} />
      </button>
    </div>
  );
}
