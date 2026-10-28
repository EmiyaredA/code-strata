function rankedLayout(objects, relations, { width = 210, height = 76, gapX = 92, gapY = 36, showIsolated = false } = {}) {
  const byId = new Map(objects.map((n) => [n.id, n])), links = relations.filter((r) => byId.has(r.source) && byId.has(r.target));
  const adjacent = new Map(objects.map((n) => [n.id, []]));
  for (const r of links) adjacent.get(r.source).push(r.target);
  let serial = 0;
  const indices = /* @__PURE__ */ new Map(), low = /* @__PURE__ */ new Map(), stack = [], active = /* @__PURE__ */ new Set(), components = [];
  function visit(id) {
    indices.set(id, serial);
    low.set(id, serial++);
    stack.push(id);
    active.add(id);
    for (const next of adjacent.get(id)) {
      if (!indices.has(next)) {
        visit(next);
        low.set(id, Math.min(low.get(id), low.get(next)));
      } else if (active.has(next)) low.set(id, Math.min(low.get(id), indices.get(next)));
    }
    if (low.get(id) === indices.get(id)) {
      const members = [];
      let member;
      do {
        member = stack.pop();
        active.delete(member);
        members.push(member);
      } while (member !== id);
      components.push(members.sort());
    }
  }
  for (const n of objects) if (!indices.has(n.id)) visit(n.id);
  const componentOf = new Map(components.flatMap((members, i) => members.map((id) => [id, i]))), indegree = components.map(() => 0), out = components.map(() => /* @__PURE__ */ new Set()), rank = components.map(() => 0);
  for (const r of links) {
    const a = componentOf.get(r.source), b = componentOf.get(r.target);
    if (a !== b && !out[a].has(b)) {
      out[a].add(b);
      indegree[b]++;
    }
  }
  const queue = indegree.map((n, i) => n === 0 ? i : null).filter((n) => n !== null);
  for (let i = 0; i < queue.length; i++) for (const b of out[queue[i]]) {
    rank[b] = Math.max(rank[b], rank[queue[i]] + 1);
    if (--indegree[b] === 0) queue.push(b);
  }
  const connected = new Set(links.flatMap((r) => [r.source, r.target])), isolated = objects.filter((n) => !connected.has(n.id));
  const columns = /* @__PURE__ */ new Map();
  for (const n of objects) {
    if (!connected.has(n.id)) continue;
    const col = rank[componentOf.get(n.id)];
    if (!columns.has(col)) columns.set(col, []);
    columns.get(col).push(n);
  }
  const positioned = [], headers = [];
  for (const [column, items] of [...columns].sort((a, b) => a[0] - b[0])) {
    items.sort((a, b) => (a.name || a.title || a.id).localeCompare(b.name || b.title || b.id));
    headers.push({ id: `lane:${column}`, name: column === 0 ? "引用起点（本范围）" : `依赖第 ${column} 层`, x: column * (width + gapX), y: 0, width });
    items.forEach((n, i) => positioned.push({ id: n.id, object: n, x: column * (width + gapX), y: 66 + i * (height + gapY), width, height, cyclic: components[componentOf.get(n.id)].length > 1 || links.some((r) => r.source === n.id && r.target === n.id) }));
  }
  if (showIsolated || !connected.size) {
    const top = positioned.length ? Math.max(...positioned.map((n) => n.y + n.height)) + 80 : 66;
    headers.push({ id: "lane:isolated", name: "无已解析关联", x: 0, y: top - 48, width: width * 2 });
    isolated.forEach((n, i) => positioned.push({ id: n.id, object: n, x: i % 3 * (width + gapX), y: top + Math.floor(i / 3) * (height + gapY), width, height, isolated: true }));
  }
  const visible = new Set(positioned.map((n) => n.id));
  return { nodes: positioned, headers, edges: links.filter((r) => visible.has(r.source) && visible.has(r.target)).map((r) => ({ ...r, cycle: componentOf.get(r.source) === componentOf.get(r.target) })), isolatedCount: isolated.length };
}
function focusLayout(objects, relations, focusId, { upstream = "调用方", downstream = "被调用方", focusTitle = "当前函数", showUnknown = false, width = 216, height = 92 } = {}) {
  const byId = new Map(objects.map((n) => [n.id, n])), focus = byId.get(focusId);
  if (!focus) return rankedLayout(objects, relations, { width, height, showIsolated: true });
  const calls = relations.filter((r) => ["calls", "imports", "unresolved-call", "references"].includes(r.kind) && byId.has(r.source) && byId.has(r.target));
  const unknown = objects.filter((n) => n.kind === "call" && n.status === "unresolved");
  const upstreamNodes = /* @__PURE__ */ new Set(), downstreamNodes = /* @__PURE__ */ new Set();
  for (const r of calls) {
    if (r.target === focusId && r.source !== focusId) upstreamNodes.add(r.source);
    if (r.source === focusId && r.target !== focusId && (!unknown.some((n) => n.id === r.target) || showUnknown)) downstreamNodes.add(r.target);
  }
  const positions = [], edges = [], headers = [{ id: "lane:upstream", name: upstream, x: 0, y: 0, width }, { id: "lane:focus", name: focusTitle, x: width + 84, y: 0, width }, { id: "lane:downstream", name: downstream, x: (width + 84) * 2, y: 0, width }];
  const rows = Math.max(1, upstreamNodes.size, downstreamNodes.size + (unknown.length && !showUnknown ? 1 : 0)), center = 66 + Math.min(1, Math.floor((rows - 1) / 2)) * (height + 28) + (rows <= 2 && calls.some((r) => r.source === focusId && r.target === focusId) ? 100 : 0);
  const create = (id, side, index, ids) => {
    let n = byId.get(id);
    if (side === "upstream" && n.kind === "file" && focus.kind !== "file") {
      const site = calls.find((r) => r.source === id && r.target === focusId);
      n = { ...n, moduleTopLevel: true, range: site?.range || n.range };
    }
    const key = side === "focus" ? id : `${side}:${id}`;
    positions.push({ id: key, object: n, x: side === "upstream" ? 0 : side === "focus" ? width + 84 : (width + 84) * 2, y: side === "focus" ? center : 66 + index * (height + 28), width, height: side === "focus" && ["function", "method", "constructor", "lambda"].includes(n.kind) ? 116 : height, role: side, mutual: upstreamNodes.has(id) && downstreamNodes.has(id) });
    return key;
  };
  create(focusId, "focus", 0);
  [...upstreamNodes].forEach((id, i) => create(id, "upstream", i));
  [...downstreamNodes].forEach((id, i) => create(id, "downstream", i));
  for (const r of calls) {
    if (r.source === focusId && r.target === focusId) {
      edges.push({ ...r, cycle: true });
      continue;
    }
    if (r.source === focusId && downstreamNodes.has(r.target)) edges.push({ ...r, target: `downstream:${r.target}` });
    else if (r.target === focusId && upstreamNodes.has(r.source)) edges.push({ ...r, source: `upstream:${r.source}` });
  }
  const placeholder = (side, label, index) => positions.push({ id: `ui:empty:${side}`, object: { id: `ui:empty:${side}`, kind: "empty", name: label, status: "empty" }, x: side === "upstream" ? 0 : (width + 84) * 2, y: 66 + index * (height + 28), width, height: 72, role: "empty" });
  if (!upstreamNodes.size) placeholder("upstream", upstream.includes("文件") || upstream.includes("模块") ? "本范围未发现已解析引用方" : "本范围未发现已解析调用方", 0);
  if (!downstreamNodes.size && !unknown.length) placeholder("downstream", downstream.includes("文件") || downstream.includes("模块") ? "本范围未发现已解析被引用方" : "本范围未发现已解析被调用方", 0);
  if (unknown.length && !showUnknown) {
    const id = "ui:unknown";
    positions.push({ id, object: { id, kind: "summary", name: `${unknown.length} 处未解析调用`, status: "unresolved", count: unknown.length }, x: (width + 84) * 2, y: 66 + downstreamNodes.size * (height + 28), width, height: 80, role: "summary" });
    edges.push({ id: "ui:unknown-edge", source: focusId, target: id, kind: "unresolved-call", status: "unresolved" });
  }
  return { nodes: positions, headers, edges, unknownCount: unknown.length };
}
export {
  focusLayout,
  rankedLayout
};

// Fit the known card geometry, independent of React Flow's transient measurement cache.
export function layoutViewport(projection, width, height) {
  const cards = [...projection.nodes, ...(projection.headers || []).map(h => ({...h,height:40}))];
  if (!cards.length) return {x:24,y:56,zoom:1};
  const left = Math.min(...cards.map(n=>n.x)), top = Math.min(...cards.map(n=>n.y));
  const spanX = Math.max(...cards.map(n=>n.x+n.width))-left;
  const spanY = Math.max(...cards.map(n=>n.y+n.height))-top;
  const zoom = Math.max(.2,Math.min(1,(width-64)/Math.max(1,spanX),(height-100)/Math.max(1,spanY)));
  return {x:(width-spanX*zoom)/2-left*zoom,y:52+(height-76-spanY*zoom)/2-top*zoom,zoom};
}
