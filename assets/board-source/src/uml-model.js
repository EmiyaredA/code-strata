export const UML_TYPES = { activity: '活动图', sequence: '时序图', class: '类图', component: '组件图', state: '状态图', usecase: '用例图', deployment: '部署图', legacy: '旧版阅读图' };
export const tabKey = project => 'code-strata:uml:' + project;
export const versionKey = diagram => `${diagram.id}:${diagram.revision}`;
export function restoreTabs(saved, available) {
  const ids = new Set(available.map(d => d.id));
  const tabs = [...new Set((saved?.tabs || []).filter(id => ids.has(id)))];
  return { tabs, active: tabs.includes(saved?.active) ? saved.active : tabs[0] || null };
}
export function closeTab(state, id) {
  const index = state.tabs.indexOf(id), tabs = state.tabs.filter(t => t !== id);
  return { ...state, tabs, active: state.active === id ? tabs[Math.min(index, tabs.length - 1)] || null : state.active };
}
export function elementEvidence(model, element) {
  if (!element) return [];
  const own = element.evidence || [];
  const endpoints = element.source ? model.nodes.filter(n => [element.source, element.target].includes(n.id)).flatMap(n => n.evidence || []) : [];
  return [...new Map([...own, ...endpoints].map(r => [`${r.path}:${r.startLine}:${r.locationKind}`, r])).values()];
}
export function selectionFiles(model, element) {
  return [...new Set(elementEvidence(model, element).map(r => r.path))];
}
export function freshnessText(check) {
  if (!check) return '待检查源码变化';
  const labels = { modified: '已修改', deleted: '已删除', error: '无法检查' };
  return [check.analyzerChanged ? '分析器已变化，需重新分析' : '', ...check.files.filter(f => f.status !== 'current').map(f => `${f.path} · ${labels[f.status]}`)].filter(Boolean).join('\n') || '关联源码未变化';
}
export function requestGate() {
  let serial = 0;
  return { next: () => ++serial, current: token => token === serial, invalidate: () => ++serial };
}

export function nodeSize(node, type) {
  if (['start', 'end'].includes(node.role)) return { width: 30, height: 30 };
  if (['fork', 'join'].includes(node.role)) return { width: 110, height: 10 };
  if (['decision', 'choice', 'merge'].includes(node.role)) return { width: 116, height: 88 };
  if (node.role === 'actor') return { width: 140, height: 104 };
  const width = type === 'sequence' ? 180 : node.role === 'usecase' ? 180 : 200;
  return { width, height: Math.max(70, 56 + (node.members?.length || 0) * 22) };
}

// Sequence diagrams use message order, not a dependency layout: each message
// attaches to its own position along a participant's lifetime.
export function sequenceProjection(model) {
  const messages = [...model.edges].sort((a, b) => a.order - b.order);
  const height = Math.max(280, 125 + messages.length * 66);
  const nodes = model.nodes.map((n, i) => ({ id: n.id, type: 'uml', position: { x: i * 260, y: 0 },
    width: 180, height, style: { width: 180, height }, data: { node: n, sequence: true, messages, height } }));
  const edges = messages.map((e, i) => ({ ...e, sourceHandle: `${e.id}-out`, targetHandle: `${e.id}-in`, sequenceIndex: i }));
  return { nodes, edges };
}

// A straight activity chain is easier to read as a wrapped route than as a
// very tall column. Only unbranched chains qualify; semantic edges never change.
export function wrapActivity(projection, model) {
  if(model.type!=='activity'||model.nodes.length<4||model.nodes.some(n=>n.parentId)||model.edges.length!==model.nodes.length-1)return projection;
  const outgoing=new Map(),incoming=new Map();
  for(const e of model.edges){if(outgoing.has(e.source)||incoming.has(e.target))return projection;outgoing.set(e.source,e);incoming.set(e.target,e);}
  const roots=model.nodes.filter(n=>!incoming.has(n.id));if(roots.length!==1)return projection;
  const order=[],seen=new Set();let id=roots[0].id;
  while(id&&!seen.has(id)){seen.add(id);order.push(id);id=outgoing.get(id)?.target;}
  if(order.length!==model.nodes.length)return projection;
  const byId=new Map(projection.nodes.map(n=>[n.id,n])),cells=new Map();
  const columns=3,cellWidth=Math.max(...projection.nodes.map(n=>n.width)),cellHeight=Math.max(...projection.nodes.map(n=>n.height));
  order.forEach((id,i)=>{const row=Math.floor(i/columns),column=row%2?columns-1-i%columns:i%columns,n=byId.get(id);cells.set(id,{row,column});n.position={x:column*(cellWidth+70)+(cellWidth-n.width)/2,y:row*(cellHeight+70)+(cellHeight-n.height)/2};});
  return {...projection,edges:model.edges.map(e=>{const a=cells.get(e.source),b=cells.get(e.target);return {...e,sourceHandle:a.row!==b.row?'bottom':a.column<b.column?'right':'left-out',targetHandle:a.row!==b.row?'top':a.column<b.column?'left':'right-in'};})};
}

export async function umlProjection(model) {
  if (model.type === 'sequence') return sequenceProjection(model);
  const { default: ELK } = await import('elkjs/lib/elk.bundled.js');
  const elk = new ELK();
  const containers = new Set(model.nodes.map(n => n.parentId).filter(Boolean));
  const graphNodes = new Map(model.nodes.map(n => [n.id, { id: n.id, ...nodeSize(n, model.type), ...(containers.has(n.id) ? { children: [], layoutOptions: { 'elk.padding': '[top=48,left=24,bottom=24,right=24]' } } : {}) }]));
  const roots = [];
  for (const n of model.nodes) {
    const shape = graphNodes.get(n.id);
    if (n.parentId) graphNodes.get(n.parentId).children.push(shape);
    else roots.push(shape);
  }
  const graph = await elk.layout({ id: 'root', layoutOptions: {
    'elk.algorithm': 'layered', 'elk.direction': model.type === 'activity' || model.type === 'state' ? 'DOWN' : 'RIGHT',
    'elk.hierarchyHandling': 'INCLUDE_CHILDREN', 'elk.spacing.nodeNode': '48', 'elk.layered.spacing.nodeNodeBetweenLayers': '70',
    'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
  }, children: roots, edges: model.edges.map(e => ({ id: e.id, sources: [e.source], targets: [e.target] })) });
  const positions = new Map();
  function visit(children) { for (const n of children || []) { positions.set(n.id, n); visit(n.children); } }
  visit(graph.children);
  // Parents must precede children for React Flow's coordinate system.
  const sorted = [];
  function add(node) { if (sorted.includes(node)) return; if (node.parentId) add(model.nodes.find(n => n.id === node.parentId)); sorted.push(node); }
  model.nodes.forEach(add);
  return wrapActivity({ nodes: sorted.map(n => { const pos = positions.get(n.id); return { id: n.id, type: 'uml', parentId: n.parentId, extent: n.parentId ? 'parent' : undefined,
    position: { x: pos.x, y: pos.y }, width: pos.width, height: pos.height, style: { width: pos.width, height: pos.height, zIndex: containers.has(n.id) ? -1 : 1 },
    data: { node: n, container: containers.has(n.id), diagramType: model.type } }; }), edges: model.edges }, model);
}
