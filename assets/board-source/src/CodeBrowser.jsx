import React, { useEffect, useMemo, useRef, useState } from "react";
import { ReactFlowProvider } from "@xyflow/react";
import { ArrowLeft, ChevronRight, FileCode2, Braces, Variable, Search, LoaderCircle, Info, ArrowUpRight, ChevronDown } from "lucide-react";
import { CodeGraph } from "./CodeGraph.jsx";
import {usePanelResize, PanelResize} from "./PanelResize.jsx";
import { Tree } from "./CodeTree.jsx";
import { parents } from "./model.js";
import { codeQuery, containsRange, frameKey, functionKinds, innermost, kindNames } from "./code-model.js";
import "./code-browser.css";
import { highlightedLines, sliceTokens } from "./syntax.js";
import { SyntaxText } from "./SyntaxCode.jsx";
const accessNames = { read: "读取", write: "赋值", readwrite: "读写", delete: "删除", type: "类型引用" };
function SourcePanel({ file, selection, references = [], onSelect, onLine }) {
  const target = useRef(null), scroll = useRef(null);
  const syntax = useMemo(() => highlightedLines(file?.content || "", file?.language, file?.path), [file?.content, file?.language, file?.path]);
  const referenceLines = useMemo(() => {
    const byLine = /* @__PURE__ */ new Map();
    for (const ref of references) if (ref.path === file?.id && ref.range.start[0] === ref.range.end[0]) {
      const line = ref.range.start[0];
      if (!byLine.has(line)) byLine.set(line, []);
      byLine.get(line).push(ref);
    }
    for (const refs of byLine.values()) refs.sort((a, b) => a.range.start[1] - b.range.start[1]);
    return byLine;
  }, [references, file?.id]);
  useEffect(() => {
    target.current?.scrollIntoView({ block: "center", behavior: "instant" });
  }, [file?.id, selection?.id]);
  if (typeof file?.content !== "string") return <div className="code-empty"><Info size={20} /><p>{file ? "该文件没有可预览的源码快照。" : "选择对象查看对应源码。"}</p></div>;
  return <div className="inline-source" ref={scroll} tabIndex={0} aria-label={`源码 ${file.path}`}>
    {file.content.split("\n").map((text, i) => {
    const line = i + 1, active = selection?.range && line >= selection.range.start[0] && line <= selection.range.end[0] && selection.path === file.id;
    const tokens = referenceLines.get(line) || [];
    const pieces = [];
    let last = 0;
    for (const r of tokens) {
      const [start, end] = [r.range.start[1], r.range.end[1]];
      if (start < last) continue;
      pieces.push(<SyntaxText key={`text-${last}`} tokens={sliceTokens(syntax[i], last, start)} />);
      pieces.push(<button key={r.id} className={`source-symbol ${selection?.id === r.id || selection?.id === r.symbolId ? "is-selected" : ""}`} title={`${r.name} · ${accessNames[r.access] || "引用"}`} onClick={(e) => {
        e.stopPropagation();
        onSelect(r);
      }}><SyntaxText tokens={sliceTokens(syntax[i], start, end)} /></button>);
      last = end;
    }
    pieces.push(<SyntaxText key={`text-${last}`} tokens={sliceTokens(syntax[i], last)} />);
    return <div key={i} className={`inline-source-line ${active ? "is-target" : ""}`} ref={active && line === selection.range.start[0] ? target : null}>
        <button className="line-number" onClick={() => onLine({ start: [line, 0], end: [line, text.length] })} aria-label={`定位第 ${line} 行`}>{line}</button><code onClick={() => onLine({ start: [line, 0], end: [line, text.length] })}>{pieces.length ? pieces : " "}</code>
      </div>;
  })}
  </div>;
}
function ObjectList({ objects, onSelect, onEnter, selection, empty = "没有可展示的对象" }) {
  return <div className="code-object-list">{objects.length ? objects.map((n) => <div className={`code-object-row ${selection?.id === n.id ? "is-active" : ""}`} key={n.id}>
    <button className="code-object-main" onClick={() => onSelect(n)} onDoubleClick={() => onEnter(n)} title={`${n.path}:${n.range.start[0]}`}><span>{n.kind === "variable" || n.kind === "parameter" ? <Variable size={14} /> : <Braces size={14} />}<strong>{n.name}</strong></span><small>{n.typeLabel || kindNames[n.kind] || n.kind} · L{n.range.start[0]}{n.capture ? " · 捕获" : ""}</small></button>
    {(functionKinds.has(n.kind) || n.kind === "file") && <button className="icon-button" aria-label={`进入 ${n.name}`} onClick={() => onEnter(n)}><ArrowUpRight size={14} /></button>}
  </div>) : <p className="code-muted-empty">{empty}</p>}</div>;
}
function CodeBrowser({ data, entry, active, onArchitecture }) {
  const split = usePanelResize("code",440);
  const [treeExpanded, setTreeExpanded] = useState(/* @__PURE__ */ new Set()), [objectContext, setObjectContext] = useState(null);
  const [frames, setFrames] = useState([]), [position, setPosition] = useState(0), [result, setResult] = useState(null), [loading, setLoading] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [selection, setSelection] = useState(null), [variable, setVariable] = useState(null), [tab, setTab] = useState("source"), [search, setSearch] = useState(""), [matches, setMatches] = useState([]), [moreBusy, setMoreBusy] = useState(false), [occurrences, setOccurrences] = useState(null), [showNotes, setShowNotes] = useState(false);
  const cache = useRef(/* @__PURE__ */ new Map()), frameStates = useRef(/* @__PURE__ */ new Map()), serial = useRef(0), root = useRef(data.project.root), current = frames[position];
  const key = current ? frameKey(current) : "", currentRef = useRef(current);
  currentRef.current = current;
  function save() {
    if (currentRef.current) frameStates.current.set(frameKey(currentRef.current), { selection, variable, tab, treeExpanded, viewport: currentRef.current.viewport });
  }
  function navigate(next) {
    save();
    const old = frameStates.current.get(frameKey(next));
    next = { ...next, viewport: old?.viewport };
    setFrames((f) => [...f.slice(0, position + 1), next]);
    setPosition(position + 1);
    setSearch("");
    setMatches([]);
  }
  useEffect(() => {
    if (!entry) return;
    const next = { view: entry.view || "files", focusId: entry.focusId, groupId: entry.groupId, path: entry.path, title: entry.title || "文件依赖" };
    if (root.current !== data.project.root) {
      root.current = data.project.root;
      frameStates.current.clear();
      cache.current.clear();
    }
    setFrames([next]);
    setPosition(0);
    setError("");
    setNotice("");
    setTreeExpanded(new Set(next.path ? parents(next.path) : []));
    setTab(next.view === "files" ? "tree" : "source");
  }, [entry?.serial, data.project.root]);
  useEffect(() => {
    cache.current.clear();
    setNotice(frames.length ? "源码快照已更新；正在核对当前对象。" : "");
  }, [data.snapshot.id, data.snapshot.mappingHash]);
  useEffect(() => {
    if (!active || !current) return;
    const control = new AbortController(), run = ++serial.current;
    const cached = cache.current.get(data.snapshot.id + ":" + key), state = frameStates.current.get(key);
    setSelection(state?.selection || cached?.focus || null);
    setVariable(state?.variable || null);
    setTab(state?.tab || (current.view === "files" ? "tree" : "source"));
    setOccurrences(null);
    setShowNotes(false);
    setTreeExpanded(state?.treeExpanded || new Set(current.path ? parents(current.path) : []));
    setResult(cached || null);
    setLoading(!cached);
    setError("");
    if (cached) return () => control.abort();
    codeQuery(data.snapshot.id, { view: current.view, focusId: current.focusId, groupId: current.groupId, hops: current.hops || 1 }, control.signal).then((next) => {
      if (run !== serial.current) return;
      cache.current.set(data.snapshot.id + ":" + key, next);
      setResult(next);
      setLoading(false);
      if (next.status === "failed") setError(next.diagnostics?.map((d) => d.message).join("；") || "代码分析失败");
      else {
        const objects = [...next.nodes || [], ...next.symbols || [], ...next.variables || [], ...next.references || [], ...(next.focus ? [next.focus] : [])];
        setSelection(objects.find(n=>n.id===state?.selection?.id) || next.focus || null);
        setVariable((next.variables || []).find(n=>n.id===state?.variable?.id) || (["variable","parameter"].includes(next.focus?.kind) ? next.focus : null));
        if (next.focus && current.view !== "files" && current.title !== next.focus.name) setFrames(list=>list.map((f,i)=>i===position?{...f,title:next.focus.name}:f));
      }
    }).catch((e) => {
      if (e.name === "AbortError" || run !== serial.current) return;
      setLoading(false);
      setError(e.message);
      if ((current.view !== "files" || current.groupId) && current.path) {
        setNotice("当前对象已变化，返回对应文件。");
        setFrames([{ view: "files", focusId: current.path, path: current.path, title: current.path.split("/").at(-1) }]);
        setPosition(0);
      }
    });
    return () => control.abort();
  }, [key, current?.hops, active, data.snapshot.id, data.snapshot.mappingHash]);
  useEffect(() => {
    if (!search.trim()) {
      setMatches([]);
      return;
    }
    const control = new AbortController(), timer = setTimeout(() => {
      codeQuery(data.snapshot.id, { view: "search", text: search, limit: 20 }, control.signal).then((r) => setMatches(r.nodes || [])).catch((e) => {
        if (e.name !== "AbortError") setNotice(e.message);
      });
    }, 220);
    return () => {
      clearTimeout(timer);
      control.abort();
    };
  }, [search, data.snapshot.id]);
  useEffect(() => {
    if (!variable) {
      setOccurrences(null);
      return;
    }
    const control = new AbortController();
    codeQuery(data.snapshot.id, { view: "references", focusId: variable.id }, control.signal).then(setOccurrences).catch((e) => {
      if (e.name !== "AbortError") setNotice(e.message);
    });
    return () => control.abort();
  }, [variable?.id, data.snapshot.id]);
  useEffect(() => {
    if (!active || !selection || !(selection.kind === "file" || functionKinds.has(selection.kind))) return;
    const control = new AbortController();
    setObjectContext(null);
    codeQuery(data.snapshot.id, { view: "symbols", focusId: selection.id }, control.signal).then(setObjectContext).catch((e) => {
      if (e.name !== "AbortError") setNotice(e.message);
    });
    return () => control.abort();
  }, [active, selection?.id, data.snapshot.id]);
  const details = objectContext && objectContext.focus?.id === selection?.id ? objectContext : result;
  const allObjects = [...result?.nodes || [], ...result?.symbols || [], ...details?.variables || [], ...occurrences?.nodes || []];
  const byId = new Map(allObjects.map((n) => [n.id, n]));
  const selectedFileId = selection?.path || variable?.path || result?.focus?.path || current?.path;
  const source = data.files.find((f) => f.id === selectedFileId);
  const refs = useMemo(() => {
    const scoped = occurrences?.nodes?.filter((n) => n.kind === "reference") || [];
    return [...new Map([...result?.references || [], ...details?.references || [], ...scoped].map((n) => [n.id, n])).values()];
  }, [result, details, occurrences]);
  const related = useMemo(() => {
    const ids = new Set(variable ? [variable.id] : []);
    if (variable && current?.view === "logic" && variable.path === current.path) {
      const definition = innermost(result?.nodes || [], variable.range);
      if (definition) ids.add(definition.id);
    }
    if (variable && current?.view === "logic") for (const ref of refs.filter((r) => r.symbolId === variable.id)) {
      const statement = innermost(result?.nodes || [], ref.range);
      if (statement && statement.path === ref.path) ids.add(statement.id);
    }
    return ids;
  }, [variable, refs, result, current?.view]);
  function choose(n) {
    if (n.kind === "relation") {
      const site = result?.references?.find((x) => x.id === n.siteId);
      setSelection(site || { ...n, path: n.path || n.evidence?.from, range: n.range || { start: [n.evidence?.line || 1, 0], end: [n.evidence?.line || 1, 0] } });
      setTab("source");
      return;
    }
    setSelection(n);
    setTab("source");
    if (["variable", "parameter"].includes(n.kind)) setVariable(n);
    if (n.kind === "reference" && n.symbolId) {
      const v = byId.get(n.symbolId);
      if (v && ["variable", "parameter"].includes(v.kind)) setVariable(v);
    }
  }
  function enter(n) {
    if (n.kind === "file") {
      navigate({ view: "functions", focusId: n.id, path: n.path, title: n.path.split("/").at(-1) });
      return;
    }
    if (n.kind === "class") {
      navigate({ view: "functions", focusId: n.id, path: n.path, title: n.name });
      return;
    }
    if (functionKinds.has(n.kind)) {
      const already = current?.view === "functions" && result?.focus?.id === n.id;
      navigate({ view: already ? "logic" : "functions", focusId: n.id, path: n.path, title: n.name });
      return;
    }
    if (n.kind === "reference" || ["variable", "parameter"].includes(n.kind)) {
      choose(n);
      return;
    }
    if (n.folded) {
      const fn = (result?.symbols || []).find((x) => containsRange(n.range, x.range) && functionKinds.has(x.kind));
      if (fn) navigate({ view: "functions", focusId: fn.id, path: fn.path, title: fn.name });
    }
  }
  async function changeWindow(patch) {
    setMoreBusy(true);
    try {
      const next=await codeQuery(data.snapshot.id,{view:current.view,focusId:current.focusId,groupId:current.groupId,hops:current.hops||1,offset:result?.offset||0,...patch});
      cache.current.set(data.snapshot.id+':'+key,next);setResult(next);
    } catch(e) {setNotice(e.message);} finally {setMoreBusy(false);}
  }
  async function more() {
    if (!result?.nextOffset) return;
    setMoreBusy(true);
    try {
      const next = await codeQuery(data.snapshot.id, { view: current.view, focusId: current.focusId, groupId: current.groupId, hops: current.hops || 1, offset: result.nextOffset });
      cache.current.set(data.snapshot.id + ":" + key, next);
      setResult(next);
    } catch (e) {
      setNotice(e.message);
    } finally {
      setMoreBusy(false);
    }
  }
  const selectedTitle = selection?.kind === "relation" ? "关系依据" : selection?.name || result?.focus?.name || "选择对象";
  const functions = (details?.symbols || []).filter((n) => functionKinds.has(n.kind));
  if (!current) return null;
  return <div className="code-browser" style={{ display: active ? "flex" : "none" }}>
    <div className="code-navigation">
      <div className="code-breadcrumb"><button onClick={() => {
    save();
    onArchitecture();
  }}><ArrowLeft size={14} />系统架构</button>{frames.slice(0, position + 1).map((f, i) => <React.Fragment key={i}><ChevronRight size={13} /><button className={i === position ? "is-current" : ""} onClick={() => {
    save();
    setPosition(i);
  }} title={f.path || f.title}>{i === 0 ? "文件依赖" : f.view === "logic" ? "逻辑与变量" : f.title}</button></React.Fragment>)}</div>
      <div className="code-search"><Search size={14} /><input aria-label="查找函数或变量" placeholder="查找函数或变量" value={search} onChange={(e) => setSearch(e.target.value)} />{search && <button className="text-button" onClick={() => setSearch("")}>收起</button>}{search && matches.length > 0 && <div className="code-search-results"><ObjectList objects={matches} selection={selection} onSelect={(n) => {
    if (n.kind === "file" || functionKinds.has(n.kind)) enter(n);
    else {
      navigate({ view: "references", focusId: n.id, path: n.path, title: n.name });
      setVariable(n);
    }
    setSearch("");
  }} onEnter={enter} /></div>}</div>
    </div>
    <main ref={split.ref} style={split.style} className={`board-layout workspace code-workspace ${tab === "source" ? "has-source" : ""}`}>
      <section className="architecture-panel code-main-panel">
        <div className="panel-header"><div className="section-title"><h2>{current.view === "files" ? "文件依赖" : current.view === "logic" ? "逻辑与变量" : current.view === "references" ? "变量引用" : "函数关系"}</h2><span className="code-scope-label" title={current.path}>{result?.focus?.name || current.title}</span></div>
          <div className="panel-actions">{result?.focus && functionKinds.has(result.focus.kind) && current.view === "functions" && <button className="text-button" onClick={() => navigate({ ...current, view: "logic", focusId:result.focus.id, path:result.focus.path, title: result.focus.name })}>进入逻辑与变量 <ChevronRight size={14} /></button>}{position > 0 && <button className="text-button" onClick={() => {
    save();
    setPosition(position - 1);
  }}>返回上层</button>}</div></div>
        <div className="code-canvas-body">
          {loading ? <div className="code-empty" role="status"><LoaderCircle size={24} className="spin" /><strong>{current.view === "logic" ? "正在展开函数结构" : "正在建立源码索引"}</strong><p>首次分析后，同一快照内复用。</p></div> : error ? <div className="code-empty" role="alert"><Info size={24} /><p>{error}</p><button className="text-button" onClick={() => {
    save();
    onArchitecture();
  }}>返回系统架构</button></div> : result?.nodes.length ? <ReactFlowProvider key={key}><CodeGraph result={result} selection={selection} related={related} selectedVariable={current.view === "logic" ? variable : null} onSelect={choose} onEnter={enter} frame={current} onViewport={(v) => {
    current.viewport = v;
    const saved = frameStates.current.get(key) || {};
    frameStates.current.set(key, { ...saved, viewport: v });
  }} /></ReactFlowProvider> : <div className="code-empty"><Braces size={26} /><strong>{result?.focus?.status === "unsupported" ? "该文件暂不支持语义分析" : "当前范围没有可展示的函数或关系"}</strong><p>{result?.focus?.reason || "源码仍可在右侧查看。"}</p></div>}
        </div>
        <footer className="graph-footer"><span><span className="legend-line" />{current.view === "logic" ? "结构顺序 · 嵌套表示包含" : "静态关系"}<span className="code-dashed-legend" />候选 / 符号引用</span><span>{current.view === "logic" && variable ? related.size : result?.nodes.length || 0} 个对象{result?.offset > 0 && <button className="text-button" onClick={()=>changeWindow({offset:Math.max(0,result.offset-(result.pageSize||100))})}>上一批</button>}{result?.remaining > 0 && <button className="text-button" disabled={moreBusy} onClick={more}>{moreBusy ? "加载中" : `下一批（余 ${result.remaining}）`}</button>}{result?.edgeOffset > 0 && <button className="text-button" onClick={()=>changeWindow({edgeOffset:Math.max(0,result.edgeOffset-300)})}>上一批关系</button>}{result?.edgeRemaining > 0 && <button className="text-button" onClick={()=>changeWindow({edgeOffset:(result.edgeOffset||0)+300})}>更多关系（余 {result.edgeRemaining}）</button>}{["files", "functions"].includes(current.view) && current.focusId && (current.hops || 1) < 5 && <button className="text-button" onClick={() => {
    cache.current.delete(data.snapshot.id + ":" + key);
    current.hops = (current.hops || 1) + 1;
    setFrames([...frames]);
  }}>扩大邻域</button>}</span></footer>
      </section>
      <aside className="code-panel code-context-panel">
        <div className="panel-header"><div className="section-title"><FileCode2 size={15} className="accent" /><h2>代码上下文</h2></div><div className="code-context-tabs">{[["source", "源码"], ["objects", "结构"], ["tree", "代码树"]].map(([id, label]) => <button key={id} aria-pressed={tab === id} onClick={() => setTab(id)}>{label}</button>)}</div></div>
        <div className="code-context-heading"><strong title={selectedTitle}>{selectedTitle}</strong><small title={source?.path}>{source?.path || current.path || "选择图中对象查看源码"}</small>{selection?.reason && <p className="code-object-reason">{selection.reason}</p>}<div>{selection?.range && <span>L{selection.range.start[0]}:{selection.range.start[1] + 1}</span>}{selection?.status && <span>{selection.status === "resolved" ? "静态已解析" : selection.status === "candidate" ? "候选目标" : selection.status === "unsupported" ? "未支持" : "未解析"}</span>}</div></div>
        {selection?.sites?.length > 0 && <div className="code-call-sites"><strong>{selection.siteCount} 处调用依据</strong>{selection.sites.map((site) => <button className="text-button" key={site.id} onClick={() => setSelection({ ...selection, id: site.id, path: site.path, range: site.range })}>L{site.range.start[0]}</button>)}</div>}
        {tab === "tree" ? <Tree data={data} expanded={treeExpanded} setExpanded={setTreeExpanded} linked={new Set((result?.nodes || []).filter((n) => n.kind === "file").map((n) => n.path))} focusId={selectedFileId} onFile={(id) => {
    const file = (result?.nodes || []).find((n) => n.kind === "file" && n.path === id);
    if (file) {
      choose(file);
      setTab("tree");
    } else navigate({ view: "files", focusId: id, path: id, title: id.split("/").at(-1) });
  }} /> : tab === "source" ? <SourcePanel file={source} selection={selection} references={refs} onSelect={choose} onLine={(r) => {
    const n = innermost((result?.nodes || []).filter((n2) => n2.path === source?.id), r);
    if (n) choose(n);
  }} /> : <div className="code-structure-scroll"><h3>{current.view === "files" ? "文件内函数" : "函数与嵌套对象"}</h3><ObjectList objects={functions} selection={selection} onSelect={choose} onEnter={enter} />{current.view === "files" && <><h3>当前范围文件</h3><ObjectList objects={result?.nodes || []} selection={selection} onSelect={choose} onEnter={enter} /></>}</div>}
        {(details?.variables?.length > 0 || variable) && <section className="code-variables"><div className="detail-heading"><strong>参数与变量</strong><span className="muted">{details?.variables?.length || 1}{result?.detailTruncated ? " · 部分" : ""}</span></div><ObjectList objects={details?.variables?.length ? details.variables : [variable]} selection={variable} onSelect={choose} onEnter={choose} />{variable && <div className="variable-summary"><span>{variable.name} · 定义 L{variable.range.start[0]}</span><span>{occurrences?.totalNodes != null ? Math.max(0, occurrences.totalNodes - 1) : "…"} 处引用</span><button className="text-button" onClick={() => navigate({ view: "references", focusId: variable.id, path: variable.path, title: variable.name })}>全部引用</button><button className="text-button" onClick={() => setVariable(null)}>返回完整逻辑</button></div>}</section>}
        {tab === "tree" && functions.length > 0 && <section className="code-file-symbols"><div className="detail-heading"><strong>文件内函数</strong><span className="muted">{functions.length}</span></div><ObjectList objects={functions} selection={selection} onSelect={choose} onEnter={enter} /></section>}
      </aside>
      <PanelResize split={split}/>
    </main>
    <div className="code-browser-status" role="status"><Info size={13} /><span>{notice || result?.note || "源码快照分析 · JS/TS 与 Python"}</span>{result?.diagnosticCount > 0 && <button className="text-button" onClick={() => setShowNotes(!showNotes)}>{result.diagnosticCount} 项分析说明 <ChevronDown size={12} /></button>}</div>
    {showNotes && <div className="code-notes"><strong>分析范围与限制</strong>{result?.diagnostics?.map((d, i) => <p key={i}><code>{d.path || d.language || d.kind}{d.line ? `:${d.line}` : ""}</code> {d.message}</p>)}{result?.diagnosticCount > 100 && <p>仅展示前 100 项；完整记录可通过分析导出命令查看。</p>}</div>}
  </div>;
}
export {
  CodeBrowser,
  SourcePanel
};
