import { sourceGroups } from './source-tags.js';
export const UML_TYPES = { activity: '活动图', sequence: '时序图', class: '类图', component: '组件图', state: '状态图', usecase: '用例图', deployment: '部署图', legacy: '旧版阅读图' };
export const tabKey = project => 'code-strata:uml:' + project;
export const normalizeTagMode = value => ['full', 'expanded'].includes(value) ? 'full' : 'simple';
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
  return [...new Map([...own.map(r=>({...r,origin:'element'})), ...endpoints.map(r=>({...r,origin:'endpoint'}))].reverse().map(r => [`${r.path}:${r.startLine}:${r.locationKind}:${r.association||''}`, r])).values()].reverse();
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

export function edgeText(edge) {
  return [edge.guard ? `[${edge.guard}]` : '', ['include','extend','create','destroy'].includes(edge.role) ? `«${edge.role}»` : '', edge.label,
    edge.status === 'candidate' && !edge.label?.includes('候选') ? '候选' : edge.status === 'unresolved' && !edge.label?.includes('未解析') ? '未解析' : ''].filter(Boolean).join(' ');
}
export function routedPath(sections) {
  return sections.map(points=>points.map((p,i)=>`${i?'L':'M'}${p.x},${p.y}`).join(' ')).join(' ');
}
// Restored viewports can point at empty space after a compound graph reflows.
export function readableViewport(nodes, viewport, frame, selectedId) {
  const byId=new Map(nodes.map(n=>[n.id,n]));
  const box=n=>{let x=n.position.x,y=n.position.y,parent=n.parentId;while(parent){const p=byId.get(parent);x+=p.position.x;y+=p.position.y;parent=p.parentId;}return {x,y,width:n.data?.headerWidth||n.width,height:n.data?.headerHeight||n.height};};
  const visible=n=>{const r=box(n),x=r.x*viewport.zoom+viewport.x,y=r.y*viewport.zoom+viewport.y;return x<frame.width-24&&x+r.width*viewport.zoom>24&&y<frame.height-24&&y+r.height*viewport.zoom>24;};
  const leaves=nodes.filter(n=>!n.data?.container),chosen=byId.get(selectedId);
  if(chosen?visible(chosen):leaves.some(visible))return viewport;
  const target=chosen||leaves[0];if(!target)return viewport;const r=box(target);
  return {...viewport,x:Math.max(24,(frame.width-r.width*viewport.zoom)/2)-r.x*viewport.zoom,y:Math.max(24,(frame.height-r.height*viewport.zoom)/2)-r.y*viewport.zoom};
}

export function nodeSize(node, type, tagMode = 'simple') {
  if (['start', 'end'].includes(node.role)) return { width: 30, height: 30 };
  if (node.role === 'merge') return { width: 36, height: 36 };
  if (['fork', 'join'].includes(node.role)) return { width: 110, height: 10 };
  const groups=normalizeTagMode(tagMode)==='full'?sourceGroups(node.evidence):[],count=Math.min(2,groups.length);
  const extra = count ? groups.slice(0,2).reduce((h,g)=>h+35+Math.min(2,g.functions.length)*28+(g.functions.length>2?18:0),8)+(groups.length>2?22:0) : 0;
  if (['decision', 'choice', 'merge'].includes(node.role)) return { width: count?190:116, height: 88+extra };
  if (node.role === 'actor') return { width: count?220:140, height: 104+extra };
  const width = count ? 280 : type === 'sequence' ? 210 : node.role === 'usecase' ? 210 : 220;
  return { width, height: Math.max(70, 56 + (node.members?.length || 0) * 22)+extra };
}

// Sequence diagrams use message order, not a dependency layout: each message
// attaches to its own position along a participant's lifetime.
export function sequenceProjection(model, tagMode = 'simple', measured = {}) {
  const messages = [...model.edges].sort((a, b) => a.order - b.order);
  const sizes=model.nodes.map(n=>measured.nodes?.get(n.id)||nodeSize(n,'sequence',tagMode)),headerHeight=Math.max(60,...sizes.map(s=>s.height));
  const height = Math.max(280, headerHeight+65 + messages.length * 66);
  let x=0;
  const nodes = model.nodes.map((n, i) => {const width=sizes[i].width,position={x,y:0};x+=width+80;return { id: n.id, type: 'uml', position,
    width, height, style: { width, height }, data: { node: n, sequence: true, messages, height,headerHeight } };});
  const edges = messages.map((e, i) => ({ ...e, sourceHandle: `${e.id}-out`, targetHandle: `${e.id}-in`, sequenceIndex: i }));
  return { nodes, edges };
}

// A straight activity chain is easier to read as a wrapped route than as a
// very tall column. Only unbranched chains qualify; semantic edges never change.
export function wrapActivity(projection, model) {
  if(model.type!=='activity'||model.edges.some(e=>edgeText(e))||model.nodes.length<4||model.nodes.some(n=>n.parentId)||model.edges.length!==model.nodes.length-1)return projection;
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

export async function umlProjection(model, tagMode = 'simple', measured = {}) {
  if (model.type === 'sequence') return sequenceProjection(model,tagMode,measured);
  const { default: ELK } = await import('elkjs/lib/elk.bundled.js');
  const elk = new ELK();
  const containers = new Set(model.nodes.map(n => n.parentId).filter(Boolean));
  const sizes=new Map(model.nodes.map(n=>[n.id,measured.nodes?.get(n.id)||nodeSize(n,model.type,tagMode)]));
  const graphNodes = new Map(model.nodes.map(n => [n.id, { id: n.id, ...sizes.get(n.id), ...(containers.has(n.id) ? { children: [], layoutOptions: { 'elk.padding': `[top=${sizes.get(n.id).height+24},left=24,bottom=24,right=24]` } } : {}) }]));
  const roots = [];
  for (const n of model.nodes) {
    const shape = graphNodes.get(n.id);
    if (n.parentId) graphNodes.get(n.parentId).children.push(shape);
    else roots.push(shape);
  }
  const graph = await elk.layout({ id: 'root', layoutOptions: {
    'elk.algorithm': 'layered', 'elk.direction': model.type === 'activity' || model.type === 'state' ? 'DOWN' : 'RIGHT',
    'elk.hierarchyHandling': 'INCLUDE_CHILDREN', 'elk.edgeRouting': 'ORTHOGONAL',
    'elk.spacing.nodeNode': '56', 'elk.layered.spacing.nodeNodeBetweenLayers': '90',
    'elk.spacing.edgeEdge':'24', 'elk.spacing.edgeNode':'20', 'elk.spacing.edgeLabel':'10',
    'elk.layered.spacing.edgeEdgeBetweenLayers':'28', 'elk.layered.spacing.edgeNodeBetweenLayers':'24',
    'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
  }, children: roots, edges: model.edges.map(e => {const text=edgeText(e),label=measured.labels?.get(e.id)||{width:Math.min(220,Math.max(40,text.length*7)),height:Math.max(22,Math.ceil(text.length*7/220)*18+4)};
      return {id:e.id,sources:[e.source],targets:[e.target],...(text?{labels:[{text,...label,layoutOptions:{'elk.edgeLabels.placement':'CENTER'}}]}:{})};}) });
  const positions = new Map();
  function visit(children) { for (const n of children || []) { positions.set(n.id, n); visit(n.children); } }
  visit(graph.children);
  function origin(id) {if(!id||id==='root')return {x:0,y:0};const n=positions.get(id),p=origin(model.nodes.find(x=>x.id===id)?.parentId);return {x:n.x+p.x,y:n.y+p.y};}
  const routes=new Map();
  function collect(g){for(const e of g.edges||[]){const o=origin(e.container||g.id),shift=p=>({x:p.x+o.x,y:p.y+o.y});
    routes.set(e.id,{sections:(e.sections||[]).map(s=>[s.startPoint,...(s.bendPoints||[]),s.endPoint].map(shift)),label:e.labels?.[0]?{...e.labels[0],x:e.labels[0].x+o.x,y:e.labels[0].y+o.y}:null});}for(const child of g.children||[])collect(child);}
  collect(graph);
  // Parents must precede children for React Flow's coordinate system.
  const sorted = [];
  function add(node) { if (sorted.includes(node)) return; if (node.parentId) add(model.nodes.find(n => n.id === node.parentId)); sorted.push(node); }
  model.nodes.forEach(add);
  return wrapActivity({ nodes: sorted.map(n => { const pos = positions.get(n.id); return { id: n.id, type: 'uml', parentId: n.parentId, extent: n.parentId ? 'parent' : undefined,
    position: { x: pos.x, y: pos.y }, width: pos.width, height: pos.height, style: { width: pos.width, height: pos.height, zIndex: containers.has(n.id) ? -1 : 1 },
    data: { node: n, container: containers.has(n.id), diagramType: model.type, headerHeight:containers.has(n.id)?sizes.get(n.id).height:undefined,headerWidth:containers.has(n.id)?sizes.get(n.id).width:undefined } }; }), edges: model.edges.map(e=>({...e,route:routes.get(e.id)})) }, model);
}
