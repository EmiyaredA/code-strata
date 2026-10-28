import React, { useEffect, useLayoutEffect, useReducer, useRef, useState } from 'react';
import { ReactFlowProvider } from '@xyflow/react';
import { Braces, ChevronRight, Ellipsis, FileCode2, LoaderCircle, PanelLeftClose, PanelLeftOpen, Pin, RotateCcw } from 'lucide-react';
import { CodeGraph } from './CodeGraph.jsx';
import { canExpand, childPaths, createHierarchyState, hierarchyGraph, hierarchyName, sourceFor } from './call-hierarchy-model.js';
import './call-hierarchy.css';
const noRelatedVariables = new Set();

function NodeMenu({ step, anchor, onSource, onRoot, onClose }) {
  const ref = useRef(null);
  const [position, setPosition] = useState({ left: 0, top: 0 });
  useLayoutEffect(() => {
    const rect = anchor?.getBoundingClientRect();
    if (rect) setPosition({ left: Math.max(8, Math.min(window.innerWidth - 166, rect.right - 150)), top: Math.max(8, Math.min(window.innerHeight - 130, rect.bottom + 3)) });
  }, []);
  useEffect(() => {
    ref.current?.querySelector('button')?.focus({ preventScroll: true });
    const close = event => { if (!ref.current?.contains(event.target) && !anchor?.contains(event.target)) onClose(false); };
    const moved = () => onClose(false);
    const scrollHost = anchor?.closest('.hierarchy-tree');
    document.addEventListener('pointerdown', close);
    window.addEventListener('resize', moved);
    scrollHost?.addEventListener('scroll', moved);
    return () => { document.removeEventListener('pointerdown', close); window.removeEventListener('resize', moved); scrollHost?.removeEventListener('scroll', moved); };
  }, []);
  return <div ref={ref} style={position} className="hierarchy-node-menu" role="menu" aria-label={`${hierarchyName(step.node)} 操作`} onKeyDown={event => {
    if (event.key === 'Escape') { event.stopPropagation(); onClose(); }
    if (event.key === 'Tab') onClose(false);
    if (['ArrowDown', 'ArrowUp'].includes(event.key)) {
      event.preventDefault(); const buttons = [...ref.current.querySelectorAll('button:not(:disabled)')];
      buttons[(buttons.indexOf(document.activeElement) + (event.key === 'ArrowDown' ? 1 : buttons.length - 1)) % buttons.length]?.focus();
    }
  }}>
    <button role="menuitem" disabled={!step.relation?.sites?.length} onClick={() => onSource('call')}>查看调用处</button>
    <button role="menuitem" onClick={() => onSource('definition')}>{step.node.kind === 'call' ? '查看调用表达式' : '查看定义'}</button>
    <button role="menuitem" disabled={!canExpand(step.node)} onClick={() => onRoot(step.node)}>以此为起点</button>
  </div>;
}

export function CallHierarchy({ root, snapshotId, frame, store, onSelect, onLocate, onRoot, onLogic, onStats }) {
  const [revision, redraw] = useReducer(n => n + 1, 0), host = useRef(null), tree = useRef(null);
  const [narrow, setNarrow] = useState(false), [open, setOpen] = useState(true), [menu, setMenu] = useState(null);
  const [width, setWidth] = useState(() => {
    try { return Math.max(220, Math.min(380, Number(localStorage.getItem('code-strata:hierarchy-width')) || 260)); } catch { return 260; }
  });
  const drag = useRef(null), currentWidth = useRef(width); currentWidth.current = width;
  const state = frame.hierarchy || (frame.hierarchy = createHierarchyState(root));
  const describedRoot = store.get(state.root, state.direction)?.focus;
  if (describedRoot) { state.root = describedRoot; state.selected[0].node = describedRoot; }
  const selected = state.selected.at(-1), graph = React.useMemo(() => hierarchyGraph(state, store), [state, store, revision]);
  useEffect(() => store.subscribe(redraw), [store]);
  useEffect(() => { store.load(state.root, state.direction); }, [store, state.root.id, state.direction]);
  useLayoutEffect(() => {
    const observer = new ResizeObserver(entries => setNarrow(entries[0].contentRect.width < 720));
    observer.observe(host.current); return () => observer.disconnect();
  }, []);
  useEffect(() => { setMenu(null); }, [state.direction, selected.key]);
  function select(path, mode = 'call', site = 0) {
    state.selected = path; state.viewport = null; redraw();
    if (path.at(-1).node.kind === 'call' && path.length > 1) state.unknownExpanded.add(path.at(-2).key);
    onSelect(path.at(-1).node);
    onLocate(sourceFor(path, mode, site));
    if (canExpand(path.at(-1).node) && !path.at(-1).recursive) store.load(path.at(-1).node, state.direction);
  }
  function source(path, mode, index) { select(path, mode, index); closeMenu(); }
  function closeMenu(restore = true) {
    const key = menu; setMenu(null);
    if (key && restore) requestAnimationFrame(() => [...tree.current?.querySelectorAll('[data-menu-key]') || []].find(el => el.dataset.menuKey === key)?.focus({ preventScroll: true }));
  }
  function direction(next) {
    state.direction = next; state.selected = [{ key: 'root', node: state.root }]; state.viewport = null;
    setMenu(null); redraw(); onSelect(state.root); onLocate(sourceFor(state.selected, 'definition'));
    store.load(state.root, next);
  }
  function graphSelect(node) {
    const path = state.selected;
    if (node.kind === 'relation') {
      const at = path.findIndex(p => p.relation?.id === node.id);
      const found = at >= 0 ? path.slice(0, at + 1) : childPaths(path, store.get(selected.node, state.direction), state.direction).find(p => p.at(-1).relation.id === node.id);
      if (found) select(found);
      return;
    }
    const at = path.findIndex(p => p.node.id === node.id);
    const found = at >= 0 ? path.slice(0, at + 1) : childPaths(path, store.get(selected.node, state.direction), state.direction).find(p => p.at(-1).node.id === node.id);
    if (found) select(found);
  }
  function row(path, depth = 0) {
    const step = path.at(-1), node = step.node, expanded = state.expanded.has(step.key);
    const target = state.direction === 'outgoing' ? node : path.at(-2)?.node;
    const page = store.get(node, state.direction), expandable = canExpand(node) && !step.recursive;
    const children = expanded && expandable ? childPaths(path, page, state.direction) : [];
    const known = children.filter(child => child.at(-1).node.kind !== 'call'), unknown = children.filter(child => child.at(-1).node.kind === 'call');
    return <li key={step.key} role="treeitem" aria-label={hierarchyName(node)} aria-selected={selected.key === step.key} aria-expanded={expandable ? expanded : undefined} data-row-key={step.key}>
      <div className={`hierarchy-row ${selected.key === step.key ? 'is-selected' : ''}`} style={{ '--tree-depth': depth }}>
        <button className="hierarchy-expand" disabled={!expandable} aria-label={`${expanded ? '收起' : '展开'} ${hierarchyName(node)}`} onClick={() => {
          if (expanded) state.expanded.delete(step.key); else { state.expanded.add(step.key); store.load(node, state.direction); }
          redraw();
        }}><ChevronRight size={14} style={{ transform: expanded ? 'rotate(90deg)' : undefined }}/></button>
        <button className="hierarchy-node" title={`${hierarchyName(node)}\n${node.path}:${node.range.start[0]}`} onClick={() => select(path)}>
          <span>{node.moduleTopLevel ? <FileCode2 size={14}/> : <Braces size={14}/>}<strong>{hierarchyName(node)}{canExpand(node) && !node.moduleTopLevel ? '()' : ''}</strong>{step.key === 'root' && <Pin size={12}/>}</span>
          <small>{node.path.split('/').at(-1)}:{node.range.start[0]}{step.relation && <em>{target?.kind === 'constructor' ? '构造' : '调用'} L{step.relation.range?.start[0]}</em>}</small>
          {step.recursive ? <small className="hierarchy-status"><RotateCcw size={11}/>递归 · 返回已有祖先</small> : node.kind === 'call' || step.relation?.status === 'candidate' ? <small className="hierarchy-status">{node.kind === 'call' ? '未解析 · 仅有调用表达式' : '候选目标'}</small> : null}
        </button>
        <button className="hierarchy-menu-trigger" data-menu-key={step.key} aria-label={`${hierarchyName(node)} 操作`} aria-haspopup="menu" aria-expanded={menu === step.key} onClick={() => setMenu(menu === step.key ? null : step.key)}><Ellipsis size={15}/></button>
      </div>
      {menu === step.key && <NodeMenu step={step} anchor={[...tree.current?.querySelectorAll('[data-menu-key]') || []].find(el => el.dataset.menuKey === step.key)} onClose={closeMenu} onSource={mode => source(path, mode)} onRoot={node => { closeMenu(); onRoot(node); }}/>}
      {selected.key === step.key && step.relation?.sites?.length > 1 && <div className="hierarchy-sites" aria-label="调用位置">
        <span>{step.relation.siteCount} 处调用</span>{step.relation.sites.map((site, index) => <button key={site.id || index} title={`${site.path}:${site.range.start[0]}`} onClick={() => source(path, 'call', index)}>L{site.range.start[0]}</button>)}
        {step.relation.siteCount > step.relation.sites.length && <small>仅列出前 {step.relation.sites.length} 处</small>}
      </div>}
      {expanded && expandable && <ul role="group">
        {known.map(child => row(child, depth + 1))}
        {unknown.length > 0 && <li role="none" className="hierarchy-unknown-group"><button className="hierarchy-unknown-toggle" aria-expanded={state.unknownExpanded.has(step.key)} onKeyDown={event => event.stopPropagation()} onClick={() => {
          if (state.unknownExpanded.has(step.key)) state.unknownExpanded.delete(step.key); else state.unknownExpanded.add(step.key);
          redraw();
        }}><ChevronRight size={13} style={{transform:state.unknownExpanded.has(step.key)?'rotate(90deg)':undefined}}/>未解析调用 · {unknown.length}</button>{state.unknownExpanded.has(step.key) && <ul role="group">{unknown.map(child => row(child, depth + 1))}</ul>}</li>}
        {page?.loading && <li role="none" className="hierarchy-feedback"><LoaderCircle size={13} className="spin"/><span role="status">加载调用关系…</span></li>}
        {page?.error && <li role="none" className="hierarchy-feedback"><span role="alert">{page.error}</span><button onClick={() => store.load(node, state.direction, !!page.ready)}>重试</button></li>}
        {page?.ready && !children.length && !page.loading && !page.error && <li role="none" className="hierarchy-feedback">{state.direction === 'outgoing' ? '没有已发现的下级调用' : '没有已发现的调用方'}</li>}
        {page?.ready && (page.nextOffset != null || page.edgeRemaining > 0) && <li role="none" className="hierarchy-feedback"><button disabled={page.loading} onClick={() => store.load(node, state.direction, true)}>加载更多{page.edgeRemaining ? '关系' : `（余 ${page.remaining}）`}</button></li>}
      </ul>}
    </li>;
  }
  const showTree = !narrow || open;
  function closeDrawer() { setOpen(false); requestAnimationFrame(() => host.current?.querySelector('.hierarchy-opener')?.focus()); }
  return <div ref={host} className={`call-hierarchy ${narrow ? 'is-narrow' : ''}`} style={{ '--hierarchy-width': `${Math.min(width, 380)}px` }} onKeyDown={event => { if (event.key === 'Escape' && narrow && open && !menu) { event.preventDefault(); event.stopPropagation(); closeDrawer(); } }}>
    {narrow && !open && <button className="hierarchy-opener icon-button" aria-label="展开调用层级" onClick={() => setOpen(true)}><PanelLeftOpen size={16}/></button>}
    {showTree && <aside className="hierarchy-tree-panel" aria-label="调用层级">
      <header><strong>调用层级</strong><span>静态分析</span>{narrow && <button className="icon-button" aria-label="收起调用层级" onClick={closeDrawer}><PanelLeftClose size={15}/></button>}</header>
      <div className="hierarchy-direction">{[['outgoing', '调用了谁'], ['incoming', '被谁调用']].map(([value, label]) => <button key={value} aria-pressed={state.direction === value} onClick={() => direction(value)}>{label}</button>)}</div>
      <ul ref={tree} role="tree" aria-label={state.direction === 'outgoing' ? '被调用函数层级' : '调用方层级'} className="hierarchy-tree" onKeyDown={event => {
        if (!['ArrowDown', 'ArrowUp', 'ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key) || menu) return;
        const rows = [...tree.current.querySelectorAll('[role="treeitem"]')], rowElement = event.target.closest('[role="treeitem"]'), at = rows.indexOf(rowElement);
        if (at < 0) return; event.preventDefault();
        const expand = rowElement.querySelector(':scope > .hierarchy-row > .hierarchy-expand');
        if (event.key === 'ArrowRight') { if (rowElement.getAttribute('aria-expanded') === 'false') expand.click(); else rows[at + 1]?.querySelector('.hierarchy-node')?.focus(); }
        else if (event.key === 'ArrowLeft') { if (rowElement.getAttribute('aria-expanded') === 'true') expand.click(); else rowElement.parentElement.closest('[role="treeitem"]')?.querySelector('.hierarchy-node')?.focus(); }
        else rows[event.key === 'Home' ? 0 : event.key === 'End' ? rows.length - 1 : Math.max(0, Math.min(rows.length - 1, at + (event.key === 'ArrowDown' ? 1 : -1)))]?.querySelector('.hierarchy-node')?.focus();
      }}>{row([{ key: 'root', node: state.root }])}</ul>
      {!narrow && <div role="separator" tabIndex={0} aria-label="调整调用层级宽度" aria-orientation="vertical" aria-valuemin={220} aria-valuemax={380} aria-valuenow={width} className="hierarchy-resizer"
        onPointerDown={event => { if (event.button !== 0) return; event.preventDefault(); drag.current = { x: event.clientX, width }; event.currentTarget.setPointerCapture(event.pointerId); }}
        onPointerMove={event => { if (drag.current) setWidth(Math.max(220, Math.min(380, drag.current.width + event.clientX - drag.current.x))); }}
        onPointerUp={() => { drag.current = null; try { localStorage.setItem('code-strata:hierarchy-width', currentWidth.current); } catch {} }} onPointerCancel={() => { drag.current = null; }}
        onDoubleClick={() => { setWidth(260); try { localStorage.setItem('code-strata:hierarchy-width', '260'); } catch {} }}
        onKeyDown={event => { if (['ArrowLeft', 'ArrowRight', 'Home'].includes(event.key)) { event.preventDefault(); const next = event.key === 'Home' ? 220 : Math.max(220, Math.min(380, width + (event.key === 'ArrowLeft' ? -16 : 16))); setWidth(next); try { localStorage.setItem('code-strata:hierarchy-width', next); } catch {} } }}/>}
    </aside>}
    {narrow && open && <button className="hierarchy-backdrop" aria-label="关闭调用层级抽屉" onClick={closeDrawer}/>}
    <div className="hierarchy-graph" aria-label="当前调用分支关系图">
      <ReactFlowProvider key={`${snapshotId}:${state.root.id}:${state.direction}`}><CodeGraph result={graph} selection={selected.node} related={noRelatedVariables} frame={{ view: 'hierarchy', viewport: state.viewport }} onSelect={graphSelect} onEnter={node => { if (canExpand(node) && !node.moduleTopLevel) onLogic(node); }} onStats={onStats} onViewport={viewport => { state.viewport = viewport; }}/></ReactFlowProvider>
      {graph.truncated && <div className="hierarchy-budget" role="status">画布已达到 100 个对象 / 300 条关系的显示预算，请收起分支或以此为起点。</div>}
    </div>
  </div>;
}
