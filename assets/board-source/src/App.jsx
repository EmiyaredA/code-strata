import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Boxes,
  Search,
  FolderOpen,
  ChevronRight,
  ChevronDown,
  FileCode2,
  Folder,
  Link2,
  ArrowUpRight,
  X,
  Check,
  Info,
  RefreshCw,
  LoaderCircle,
  Settings,
  Layers,
  PanelRightOpen,
  PanelRightClose,
} from "lucide-react";
import { demo } from "./demo.js";
import { searchProject } from "./model.js";
import {
  ProjectOverview,
  InspectionPanel,
} from "./InventoryPanels.jsx";
import "./workspace-toolbar.css";
import { highlightedLines } from "./syntax.js";
import { SyntaxText } from "./SyntaxCode.jsx";
import { AgentSettings } from "./AgentSettings.jsx";
import { UmlWorkspace } from "./UmlWorkspace.jsx";
import { ExplorationWorkspace } from "./ExplorationWorkspace.jsx";
import { useChatDrawer } from "./ChatDrawer.jsx";
import { apiFetch } from './api-fetch.js';
import "@xyflow/react/dist/style.css";
const token = () =>
  document.querySelector('meta[name="architecture-token"]')?.content || "";
async function requestProject(body) {
  const response = await apiFetch("/api/project", {
    method: body ? "POST" : "GET",
    headers: {
      "X-Architecture-Token": token(),
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "读取项目失败");
  return data.demo ? demo : data;
}
function Dialog({ title, subtitle, children, onClose, wide = false, className = "", hidden = false }) {
  const ref = useRef(null),
    closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const previous = document.activeElement;
    ref.current.querySelector("input,button")?.focus();
    function keyboard(event) {
      if (!ref.current?.getClientRects().length) return;
      if (event.key === "Escape") {
        event.stopPropagation();
        closeRef.current();
      }
      if (event.key === "Tab") {
        const items = [
            ...ref.current.querySelectorAll(
              'button:not(:disabled),input:not(:disabled),select:not(:disabled),summary,a[href],[tabindex="0"]',
            ),
          ].filter((item) => item.getClientRects().length),
          first = items[0],
          last = items.at(-1);
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        }
        if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    }
    document.addEventListener("keydown", keyboard);
    return () => {
      document.removeEventListener("keydown", keyboard);
      previous?.focus();
    };
  }, []);
  return (
    <div
      className="modal-backdrop"
      style={hidden ? { display: "none" } : undefined}
      aria-hidden={hidden || undefined}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <section
        ref={ref}
        className={`dialog ${wide ? "dialog-wide" : ""} ${className}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header className="dialog-header">
          <div className="dialog-title"><strong title={title}>{title}</strong>{subtitle && <small>{subtitle}</small>}</div>
          <button
            className="icon-button"
            aria-label="关闭对话框"
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}
function ProjectDialog({ current, onLoad, onClose }) {
  const [path, setPath] = useState(current.project.root || ""),
    [mapping, setMapping] = useState(current.mappingPath || "");
  const [busy, setBusy] = useState(false),
    [picking, setPicking] = useState(false),
    [error, setError] = useState("");
  const pending = busy || picking;
  async function selectDirectory() {
    setPicking(true);
    setError("");
    try {
      const response = await apiFetch("/api/select-directory", {
        method: "POST",
        headers: {
          "X-Architecture-Token": token(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ path: path.trim() || null }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "选择文件夹失败");
      if (data.path) setPath(data.path);
    } catch (err) {
      setError(err.message);
    } finally {
      setPicking(false);
    }
  }
  async function submit(e) {
    e.preventDefault();
    if (pending) return;
    setBusy(true);
    setError("");
    try {
      onLoad(
        await requestProject({
          path: path.trim(),
          mapping: mapping.trim() || null,
        }),
      );
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title="打开本地项目"
      onClose={() => {
        if (!pending) onClose();
      }}
    >
      <form onSubmit={submit} className="project-form">
        <p>读取源码与静态引用，不执行项目中的代码。</p>
        <div className="project-directory">
          <label htmlFor="project-directory">项目目录</label>
          <div className="directory-input-row">
            <input
              id="project-directory"
              autoComplete="off"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              placeholder="输入目录绝对路径"
              required
              disabled={pending}
            />
            <button
              type="button"
              className="button directory-picker-button"
              onClick={selectDirectory}
              disabled={pending}
              aria-busy={picking}
            >
              {picking ? (
                <LoaderCircle size={15} className="spin" />
              ) : (
                <FolderOpen size={15} />
              )}
              {picking ? "正在选择" : "选择文件夹"}
            </button>
          </div>
          {picking && (
            <small role="status">请在系统窗口中选择文件夹，或取消返回。</small>
          )}
        </div>
        <label>
          架构分组文件 <span className="muted">（可选）</span>
          <input
            autoComplete="off"
            value={mapping}
            onChange={(e) => setMapping(e.target.value)}
            placeholder="映射 JSON 的绝对路径"
            disabled={pending}
          />
        </label>
        <small>
          未指定映射时，先按目录分组。可由 Skill 整理架构分组后重新加载。
        </small>
        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}
        <div className="form-actions">
          <button
            type="button"
            className="button"
            onClick={onClose}
            disabled={pending}
          >
            取消
          </button>
          <button className="button primary" disabled={pending}>
            {busy ? (
              <>
                <LoaderCircle size={15} className="spin" />
                正在扫描
              </>
            ) : (
              "打开项目"
            )}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
function SourceDialog({ file, line, onClose, onPage, onLocate, locating, locateError }) {
  const active = useRef(null);
  const syntax = useMemo(() => highlightedLines(file.content, file.language, file.path), [file.content, file.language, file.path]);
  useEffect(() => {
    active.current?.scrollIntoView({ block: "center" });
  }, [file.id, line]);
  return (
    <Dialog title={file.path} onClose={onClose} wide>
      <div className="source-meta">
        <FileCode2 size={14} />
        <span>{file.language}</span>
        <span>
          {file.evidenceOnly
            ? "扫描快照中的证据片段 · 只读"
            : "扫描快照中的源码 · 只读"}
        </span>
        {onLocate && <button className="text-button" disabled={locating} onClick={onLocate}>{locating ? "正在定位…" : "在代码地图中定位"}</button>}
        {onPage && <><span>第 {(file.lineOffset || 0) + 1}–{file.endLine} 行 / 共 {file.totalLines} 行</span>
          <button className="text-button" disabled={!file.lineOffset} onClick={() => onPage(Math.max(1, file.lineOffset - 299))}>上一段</button>
          <button className="text-button" disabled={file.endLine >= file.totalLines} onClick={() => onPage(file.endLine + 1)}>下一段</button></>}
      </div>
      {locateError && <p className="source-locate-error" role="alert">{locateError}</p>}
      <div className="source-code" tabIndex={0} aria-label="源代码">
        {file.content.split("\n").map((text, i) => (
          <div
            key={i}
            ref={i + (file.lineOffset || 0) + 1 === line ? active : null}
            className={`source-line ${i + (file.lineOffset || 0) + 1 === line ? "is-target" : ""}`}
          >
            <span className="line-number">
              {i + (file.lineOffset || 0) + 1}
            </span>
            <code>{text ? <SyntaxText tokens={syntax[i]} /> : " "}</code>
          </div>
        ))}
      </div>
    </Dialog>
  );
}
export function App() {
  const chatDrawer = useChatDrawer();
  const [data, setData] = useState(demo), [inspector, setInspector] = useState(null);
  const [overviewOpen, setOverviewOpen] = useState(false), [umlSourceEntry, setUmlSourceEntry] = useState(null);
  const entrySerial = useRef(0);
  const [modal, setModal] = useState(null),
    [query, setQuery] = useState(""),
    [searchOpen, setSearchOpen] = useState(false),
    [resultIndex, setResultIndex] = useState(0),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState("");
  const statisticsView = ["metrics", "coverage"].includes(modal?.kind) ? modal : modal?.returnTo;
  const searchRef = useRef(null);
  const results = useMemo(() => searchProject(data, query), [data, query]);
  function load(next) {
    setData(next); setInspector(null); setUmlSourceEntry(null); setOverviewOpen(false);
    setNotice(""); setQuery("");
  }
  useEffect(() => {
    requestProject()
      .then(load)
      .catch((e) => setNotice(e.message));
  }, []);
  useEffect(() => {
    function key(e) {
      if (
        e.key === "/" &&
        !document.querySelector('[role="dialog"]') &&
        !["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)
      ) {
        e.preventDefault();
        searchRef.current?.focus();
      }
    }
    document.addEventListener("keydown", key);
    return () => document.removeEventListener("keydown", key);
  }, []);
  useEffect(() => {
    if (!searchOpen) return;
    const handle = (e) => {
      if (!searchRef.current?.closest(".search-wrap")?.contains(e.target))
        setSearchOpen(false);
    };
    document.addEventListener("pointerdown", handle);
    return () => document.removeEventListener("pointerdown", handle);
  }, [searchOpen]);
  useEffect(() => {
    if (!overviewOpen) return;
    function close(e) {
      if (e.type === 'keydown' && e.key !== 'Escape') return;
      if (e.type === 'pointerdown' && e.target.closest('.uml-overview-popover,[aria-label="项目概览"]')) return;
      if (e.type === 'keydown') { e.preventDefault(); e.stopImmediatePropagation(); }
      setOverviewOpen(false);
    }
    document.addEventListener('pointerdown', close);
    document.addEventListener('keydown', close, true);
    return () => { document.removeEventListener('pointerdown', close); document.removeEventListener('keydown', close, true); };
  }, [overviewOpen]);
  function openInspection(view) {
    setOverviewOpen(false);
    if (["metrics", "coverage"].includes(view.kind)) setModal(view);
    else { setInspector(view); setModal({kind:"inventory",view}); setOverviewOpen(false); }
  }
  function inspectSource(ref) {
    const file = data.files.find((f) => f.id === ref.path);
    const returnTo = ["metrics", "coverage"].includes(modal?.kind) ? modal : null;
    if (file) setModal({ kind: "source", id: file.id, line: ref.line, returnTo });
    else if (ref.text)
      setModal({
        kind: "evidence",
        returnTo,
        file: {
          id: ref.path,
          path: ref.path,
          content: ref.text,
          language: "依据",
          evidenceOnly: true,
          lineOffset: (ref.line || 1) - 1,
        },
        line: ref.line,
      });
    else setNotice("该文件未保留可预览源码；盘点与计数不受影响。");
  }
  function select(next) {
    const path = next.kind === "file" ? next.id : data.groups.find(g=>g.id===next.id)?.files[0];
    if (path) setUmlSourceEntry({path,serial:++entrySerial.current});
    setQuery(""); setSearchOpen(false); searchRef.current?.blur();
  }
  async function refresh() {
    if (!data.project.root) return;
    setBusy(true);
    try {
      load(
        await requestProject({
          path: data.project.root,
          mapping: data.mappingPath,
        }),
      );
    } catch (e) {
      setNotice(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className={`app-shell uml-shell ${chatDrawer.open && !chatDrawer.overlay ? "has-chat-drawer" : ""}`} style={{"--chat-drawer-width": `${chatDrawer.width}px`}}>
      <header className="topbar">
        <div className="brand">
          <span className="brand-icon">
            <Boxes size={19} />
          </span>
          <h1>代码架构</h1>
          <span className="header-separator" />
          <span className="project-name" title={data.project.root}>
            {data.project.name}
          </span>
          {data.project.sample && <span className="sample-tag">示例</span>}
        </div>
        <div className="topbar-tools">
          <div
            className="snapshot"
            title={`分析输入：${data.snapshot.analysisInputHash || data.snapshot.id}\n源码指纹：${data.snapshot.sourceHash || data.snapshot.id}\n提交：${data.snapshot.commit || "未关联"}\n扫描时间：${data.snapshot.scannedAt}`}
          >
            <span className="status-dot" />
            快照 <code>{data.snapshot.id.slice(0, 8)}</code>
          </div>
          <div className="search-wrap">
            <Search size={15} />
            <input
              ref={searchRef}
              role="combobox"
              aria-label="搜索模块或源码"
              aria-expanded={searchOpen && !!query}
              aria-controls="search-results"
              aria-activedescendant={
                results[resultIndex] ? `result-${resultIndex}` : undefined
              }
              value={query}
              placeholder="搜索模块或源码"
              onFocus={() => setSearchOpen(true)}
              onChange={(e) => {
                setQuery(e.target.value);
                setSearchOpen(true);
                setResultIndex(0);
              }}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  setSearchOpen(false);
                  e.currentTarget.blur();
                }
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setResultIndex((i) => Math.min(i + 1, results.length - 1));
                }
                if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setResultIndex((i) => Math.max(0, i - 1));
                }
                if (e.key === "Enter" && results[resultIndex]) {
                  e.preventDefault();
                  select(results[resultIndex], true);
                }
              }}
            />
            <kbd>/</kbd>
            {searchOpen && query && (
              <div
                className="search-results"
                id="search-results"
                role="listbox"
              >
                {results.length ? (
                  results.map((r, i) => (
                    <button
                      key={`${r.kind}:${r.id}`}
                      id={`result-${i}`}
                      role="option"
                      aria-selected={i === resultIndex}
                      className={i === resultIndex ? "is-active" : ""}
                      onMouseEnter={() => setResultIndex(i)}
                      onClick={() => select(r, true)}
                    >
                      {r.kind === "file" ? (
                        <FileCode2 size={16} />
                      ) : (
                        <Boxes size={16} />
                      )}
                      <span>
                        <strong>{r.label}</strong>
                        <small>{r.detail}</small>
                      </span>
                    </button>
                  ))
                ) : (
                  <p>没有匹配的模块或源码</p>
                )}
              </div>
            )}
          </div>
          <button
            className="button"
            onClick={() => setModal({ kind: "project" })}
          >
            <FolderOpen size={15} />
            打开项目
          </button>
          <button className="text-button topbar-chat-toggle" data-chat-opener aria-label={chatDrawer.open ? "收起会话" : "展开会话"} aria-expanded={chatDrawer.open} onClick={() => { chatDrawer.setOpen(!chatDrawer.open); }}>{chatDrawer.open ? <PanelRightClose size={16}/> : <PanelRightOpen size={16}/>}会话</button>
          <button className="icon-button" aria-label="项目概览" title="项目概览" aria-expanded={overviewOpen} onClick={()=>setOverviewOpen(v=>!v)}><Layers size={17}/></button>
          <button className="icon-button" aria-label="打开设置" title="设置" onClick={() => setModal({ kind: "settings" })}>
            <Settings size={17} />
          </button>
        </div>
      </header>
      {overviewOpen && <section className="uml-overview-popover" role="dialog" aria-label="项目概览"><header><strong>项目概览</strong><button className="icon-button" aria-label="关闭项目概览" onClick={()=>setOverviewOpen(false)}><X size={16}/></button></header><ProjectOverview data={data} inspector={inspector} onOpen={openInspection}/><div className="uml-overview-links"><button className="text-button" onClick={()=>openInspection({kind:"technologies"})}>全部技术栈与依据</button><button className="text-button" onClick={()=>openInspection({kind:"coverage"})}>解析范围</button><button className="text-button" onClick={()=>setModal({kind:"diagnostics"})}>扫描说明</button><button className="text-button" disabled={busy} onClick={refresh}>重新扫描项目</button></div></section>}
      <UmlWorkspace data={data} drawer={chatDrawer} onRefresh={refresh} busy={busy} sourceEntry={umlSourceEntry} renderChat={props=><ExplorationWorkspace {...props} data={data} active={true} drawer={chatDrawer} SourceDialog={SourceDialog} onSettings={()=>setModal({kind:"settings"})}/>}/>

      {notice && <div className="app-status" role="status">
        <Info size={13} />
        {notice}
      </div>}
      {modal?.kind === "project" && (
        <ProjectDialog
          current={data}
          onLoad={load}
          onClose={() => setModal(null)}
        />
      )}
      {modal?.kind === "settings" && <AgentSettings Dialog={Dialog} onClose={() => setModal(null)} />}
      {modal?.kind === "inventory" && <Dialog title="技术栈与扫描依据" onClose={()=>setModal(null)} wide><InspectionPanel data={data} view={modal.view} onOpen={openInspection} onSource={inspectSource} showHeader={true}/></Dialog>}
      {statisticsView && (
        <Dialog
          title="工程统计"
          hidden={statisticsView !== modal}
          subtitle={`${data.project.name} · 当前快照 ${data.snapshot.id}`}
          onClose={() => setModal(null)}
          wide
          className="dialog-inspection dialog-statistics"
        >
          <nav className="statistics-navigation" aria-label="工程统计视图">
            <button aria-pressed={statisticsView.kind === "metrics"} onClick={() => openInspection({ kind: "metrics" })}>代码规模</button>
            <button aria-pressed={statisticsView.kind === "coverage"} onClick={() => openInspection({ kind: "coverage" })}>解析详情</button>
          </nav>
          <InspectionPanel
            data={data}
            view={statisticsView}
            onOpen={openInspection}
            onSource={inspectSource}
            showHeader={false}
          />
        </Dialog>
      )}
      {modal?.kind === "source" &&
        data.files.some((f) => f.id === modal.id) && (
          <SourceDialog
            file={data.files.find((f) => f.id === modal.id)}
            line={modal.line}
            onClose={() => setModal(modal.returnTo || null)}
          />
        )}
      {modal?.kind === "evidence" && (
        <SourceDialog
          file={modal.file}
          line={modal.line}
          onClose={() => setModal(modal.returnTo || null)}
        />
      )}
      {modal?.kind === "diagnostics" && (
        <Dialog title="扫描说明" onClose={() => setModal(null)} wide>
          <div className="diagnostics-list">
            {data.limitations.map((text, i) => (
              <p key={i}>{text}</p>
            ))}
            {data.diagnostics.map((d, i) => (
              <article key={i}>
                <strong>
                  {d.path || d.kind}
                  {d.line ? `:${d.line}` : ""}
                </strong>
                <p>{d.message}</p>
                {d.paths && <code>{d.paths.join("\n")}</code>}
              </article>
            ))}
          </div>
        </Dialog>
      )}
    </div>
  );
}
