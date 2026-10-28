import { functionKinds } from './code-model.js';

export const hierarchyKey = (id, direction) => `${direction}:${id}`;
export const canExpand = node => functionKinds.has(node.kind) || node.moduleTopLevel;
export const hierarchyName = node => node.moduleTopLevel ? `${node.path.split('/').at(-1)} · 顶层代码` : node.kind === 'call' ? node.name : node.qualifiedName || node.name;
export function createHierarchyState(root) {
  return { root, direction: 'outgoing', expanded: new Set(['root']), unknownExpanded: new Set(), selected: [{ key: 'root', node: root }], viewport: null };
}
export function childPaths(path, page, direction) {
  if (!page) return [];
  const focus = path.at(-1).node.id, nodes = new Map(page.nodes.map(n => [n.id, n]));
  return page.relations.filter(r => direction === 'outgoing' ? r.source === focus : r.target === focus).map(relation => {
    const node = nodes.get(direction === 'outgoing' ? relation.target : relation.source);
    if (!node) return null;
    return [...path, { node, relation, key: `${path.at(-1).key}/${relation.id}`, recursive: path.some(p => p.node.id === node.id) }];
  }).filter(Boolean);
}
export function sourceFor(path, mode = 'call', siteIndex = 0) {
  const step = path.at(-1), site = step.relation?.sites?.[siteIndex];
  return mode === 'call' && site?.path && site.range ? { id: site.id, path: site.path, range: site.range, locationKind: 'call' } : { id: step.node.id, path: step.node.path, range: step.node.range, locationKind: 'definition' };
}

// Cache adjacency, not visual occurrences: diamond branches have separate paths.
export class HierarchyStore {
  constructor(snapshotId, query) { this.snapshotId = snapshotId; this.query = query; this.pages = new Map(); this.listeners = new Set(); }
  subscribe = listener => { this.listeners.add(listener); return () => this.listeners.delete(listener); };
  emit() { for (const listener of this.listeners) listener(); }
  get(node, direction) { return this.pages.get(hierarchyKey(node.id, direction)); }
  async load(node, direction, more = false) {
    const key = hierarchyKey(node.id, direction), old = this.pages.get(key);
    if (old?.loading || old?.ready && !more) return;
    const control = new AbortController();
    const offset = more ? old.edgeRemaining ? old.offset : old.nextOffset : 0;
    if (offset == null) return;
    const edgeOffset = more && old.edgeRemaining ? old.edgeOffset + 300 : 0;
    const page = { ...old, loading: true, error: '', control, nodes: old?.nodes || [], relations: old?.relations || [] };
    this.pages.set(key, page); this.emit();
    try {
      const data = await this.query(this.snapshotId, { view: 'hierarchy', focusId: node.id, direction, limit: 100, offset, edgeOffset }, control.signal);
      if (control.signal.aborted || this.pages.get(key) !== page) return;
      if (data.status === 'failed') throw new Error(data.error || '源码分析失败，请重试');
      if (data.snapshotId !== this.snapshotId) throw new Error('源码快照已变化，请重新打开调用层级');
      const nodes = [...new Map([...page.nodes, ...data.nodes].map(n => [n.id, n])).values()];
      const relations = [...new Map([...page.relations, ...data.relations].map(r => [r.id, r])).values()];
      this.pages.set(key, { ...data, nodes, relations, loading: false, ready: true });
    } catch (error) {
      if (control.signal.aborted || this.pages.get(key) !== page) return;
      this.pages.set(key, { ...page, loading: false, error: error.message, control: null });
    }
    this.emit();
  }
  cancel() {
    for (const [key, page] of this.pages) if (page.loading) {
      page.control.abort();
      this.pages.set(key, { ...page, loading: false });
    }
  }
}

// Keep the selected ancestry before adding the selected node's direct neighbors.
export function hierarchyGraph(state, store) {
  const path = state.selected, nodes = new Map(), relations = new Map();
  for (const step of path) { nodes.set(step.node.id, step.node); if (step.relation) relations.set(step.relation.id, { ...step.relation, trail: true }); }
  const selected = path.at(-1).node, page = store.get(selected, state.direction);
  for (const child of childPaths(path, page, state.direction)) {
    const step = child.at(-1);
    if (!nodes.has(step.node.id) && nodes.size >= 100 || relations.size >= 300) break;
    nodes.set(step.node.id, step.node); relations.set(step.relation.id, step.relation);
  }
  return { focus: selected, nodes: [...nodes.values()], relations: [...relations.values()], hierarchy: true,
    truncated: (page?.nodes.length || 0) + path.length > 100 || (page?.relations.length || 0) + path.length > 300 };
}
