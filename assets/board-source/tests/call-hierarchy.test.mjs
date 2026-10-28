import { test } from 'node:test';
import assert from 'node:assert/strict';
import { HierarchyStore, childPaths, createHierarchyState, hierarchyGraph, sourceFor } from '../src/call-hierarchy-model.js';
const node = (id, kind = 'function') => ({ id, kind, name: id, path: `${id}.py`, range: { start: [10, 0], end: [14, 0] } });
const a = node('a'), b = node('b', 'constructor'), c = node('c');
const edge = (source, target, line = 20) => ({ id: `${source}:${target}`, kind: 'calls', source, target, status: 'resolved', siteCount: 1, sites: [{ id: `site:${line}`, path: `${source}.py`, range: { start: [line, 4], end: [line, 8] } }] });
const response = (nodes, relations, extra = {}) => ({ snapshotId: 's', status: 'ready', nodes, relations, nextOffset: null, ...extra });

test('root remains pinned while independent branches and source locations are selected', () => {
  const state = createHierarchyState(a), original = state.selected;
  const ab = edge('a', 'b'), ac = edge('a', 'c');
  const children = childPaths(original, response([a, b, c], [ab, ac]), 'outgoing');
  state.selected = children[0]; state.expanded.add(children[0].at(-1).key);
  assert.equal(state.root.id, 'a'); assert.equal(state.selected.at(-1).node.id, 'b');
  assert.equal(sourceFor(state.selected).path, 'a.py'); assert.equal(sourceFor(state.selected).range.start[0], 20);
  assert.equal(sourceFor(state.selected, 'definition').path, 'b.py'); assert.equal(sourceFor(state.selected, 'definition').range.start[0], 10);
  state.selected = children[1]; assert.ok(state.expanded.has(children[0].at(-1).key));
  // A history frame keeps this session and its viewport rather than reconstructing it from clicks.
  const frame = { hierarchy: state }; frame.hierarchy.viewport = { x: 4, y: 5, zoom: .8 };
  assert.equal(frame.hierarchy.root, a); assert.deepEqual(frame.hierarchy.viewport, { x: 4, y: 5, zoom: .8 });
});
test('incoming traversal preserves the source-to-target relation and multiple call-site identity', () => {
  const relation = edge('a', 'b'); relation.sites.push({ id: 'second', path: 'a.py', range: { start: [24, 0], end: [24, 5] } });
  const path = childPaths(createHierarchyState(b).selected, response([a, b], [relation]), 'incoming')[0];
  assert.equal(path.at(-1).node.id, 'a'); assert.equal(path.at(-1).relation.target, 'b');
  assert.equal(sourceFor(path, 'call', 1).range.start[0], 24);
});
test('recursion stops on ancestors, while diamonds keep distinct visual paths', () => {
  const state = createHierarchyState(a);
  const first = childPaths(state.selected, response([a,b], [edge('a','b')]), 'outgoing')[0];
  const cycle = childPaths(first, response([b,a], [edge('b','a')]), 'outgoing')[0];
  assert.equal(cycle.at(-1).recursive, true);
  const direct = childPaths(state.selected, response([a,c], [edge('a','c')]), 'outgoing')[0];
  const indirect = childPaths(first, response([b,c], [edge('b','c')]), 'outgoing')[0];
  assert.notEqual(direct.at(-1).key, indirect.at(-1).key); assert.equal(indirect.at(-1).recursive, false);
});
test('graph retains selected ancestry and only direct selected-node neighbors within budgets', () => {
  const state = createHierarchyState(a), store = new HierarchyStore('s', null);
  state.selected = childPaths(state.selected, response([a,b], [edge('a','b')]), 'outgoing')[0];
  store.pages.set('outgoing:b', response([b,c], [edge('b','c')]));
  const graph = hierarchyGraph(state, store);
  assert.deepEqual(graph.nodes.map(n=>n.id), ['a','b','c']); assert.equal(graph.relations.find(r=>r.id==='a:b').trail, true);
  const more = Array.from({length:130}, (_,i)=>node(`x${i}`));
  store.pages.set('outgoing:b', response([b,...more], more.map(n=>edge('b',n.id))));
  assert.equal(hierarchyGraph(state,store).nodes.length,100); assert.ok(hierarchyGraph(state,store).truncated);
});
test('cache loads one hop by direction, merges pages, and preserves partial results on retry', async () => {
  const requests = []; let fail = true;
  const store = new HierarchyStore('s', async (snapshot, body) => {
    requests.push(body); assert.equal(snapshot,'s'); assert.equal(body.view,'hierarchy');
    if (!body.offset) return response([a,b],[edge('a','b')],{offset:0,nextOffset:1,remaining:1});
    if (fail) { fail=false; throw new Error('temporary'); }
    return response([a,c],[edge('a','c')],{offset:1});
  });
  await store.load(a,'outgoing'); await store.load(a,'outgoing'); assert.equal(requests.length,1);
  await store.load(a,'outgoing',true); assert.equal(store.get(a,'outgoing').relations.length,1); assert.equal(store.get(a,'outgoing').error,'temporary');
  await store.load(a,'outgoing',true); assert.equal(store.get(a,'outgoing').relations.length,2);
  await store.load(a,'incoming'); assert.equal(requests.at(-1).direction,'incoming');
});
test('cancelled and stale snapshot responses cannot overwrite a newer branch or session', async () => {
  let finish; const pending = new Promise(resolve => {finish=resolve;});
  const store = new HierarchyStore('s', async()=>pending);
  const request = store.load(a,'outgoing'); store.cancel();
  store.query = async()=>response([a,c],[edge('a','c')]); await store.load(a,'outgoing');
  finish(response([a,b],[edge('a','b')])); await request;
  assert.equal(store.get(a,'outgoing').nodes.at(-1).id,'c');
  const changed = new HierarchyStore('new-snapshot', async()=>response([a,b],[edge('a','b')]));
  await changed.load(a,'outgoing'); assert.match(changed.get(a,'outgoing').error,/快照/); assert.equal(changed.get(a,'outgoing').nodes.length,0);
});
