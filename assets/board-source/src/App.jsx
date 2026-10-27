import React, { useEffect, useMemo, useRef, useState } from "react";
import { ReactFlowProvider } from "@xyflow/react";
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
} from "lucide-react";
import { demo } from "./demo.js";
import { parents, searchProject, selectionInfo } from "./model.js";
import {
  ProjectOverview,
  InspectionPanel,
  ModuleStatistics,
  inventoryFiles,
} from "./InventoryPanels.jsx";
import { ArchitectureGraph } from "./Graph.jsx";
import { CodeBrowser } from "./CodeBrowser.jsx";
import {usePanelResize, PanelResize} from "./PanelResize.jsx";
import { highlightedLines } from "./syntax.js";
import { SyntaxText } from "./SyntaxCode.jsx";
import { Tree } from "./CodeTree.jsx";
import "@xyflow/react/dist/style.css";
const token = () =>
  document.querySelector('meta[name="architecture-token"]')?.content || "";
async function requestProject(body) {
  const response = await fetch("/api/project", {
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
      const response = await fetch("/api/select-directory", {
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
function SourceDialog({ file, line, onClose }) {
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
      </div>
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
  const architectureSplit = usePanelResize("architecture");
  const [data, setData] = useState(demo),
    [selection, setSelection] = useState({ kind: "group", id: "save" }),
    [allTree, setAllTree] = useState(false),
    [expanded, setExpanded] = useState(
      new Set(demo.groups[0].files.flatMap(parents)),
    );
  const [inspector, setInspector] = useState(null);
  const [codeActive, setCodeActive] = useState(false), [codeEntry, setCodeEntry] = useState(null);
  const entrySerial = useRef(0);
  function browseCode(target = selection) {
    if (!data.project.root) return;
    const group = target?.kind === "group" ? data.groups.find(g => g.id === target.id) : null;
    const path = target?.kind === "file" ? target.id : group?.files[0] || info.files[0];
    setCodeEntry({serial: ++entrySerial.current, view: "files", focusId: path, path, groupId: group?.id, title: group?.title || path?.split("/").at(-1) || "文件依赖"});
    setCodeActive(true);
  }
  const [modal, setModal] = useState(null),
    [query, setQuery] = useState(""),
    [searchOpen, setSearchOpen] = useState(false),
    [resultIndex, setResultIndex] = useState(0),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState("");
  const statisticsView = ["metrics", "coverage"].includes(modal?.kind) ? modal : modal?.returnTo;
  const searchRef = useRef(null),
    panelRef = useRef(null),
    info = useMemo(() => selectionInfo(data, selection), [data, selection]),
    linked = useMemo(() => new Set(info.files), [info]);
  const focusId = selection?.kind === "file" ? selection.id : info.files[0],
    activeFile = data.files.find((f) => f.id === focusId),
    results = useMemo(() => searchProject(data, query), [data, query]);
  function load(next) {
    const sameProject = data.project.root && data.project.root === next.project.root;
    setData(next);
    if (!sameProject) { setCodeActive(false); setCodeEntry(null); }
    setInspector(null);
    const first = next.groups.find((g) => g.files.length),
      s = first
        ? { kind: "group", id: first.id }
        : inventoryFiles(next)[0]
          ? { kind: "file", id: inventoryFiles(next)[0].id }
          : null;
    const valid = sameProject && ((selection?.kind === "file" && inventoryFiles(next).some(f => f.id === selection.id)) || (selection?.kind === "group" && next.groups.some(g => g.id === selection.id)) || (selection?.kind === "edge" && next.edges.some(e => e.id === selection.id)));
    setSelection(valid ? selection : s);
    setExpanded(new Set(selectionInfo(next, s).files.flatMap(parents)));
    setAllTree(false);
    setNotice("");
    setQuery("");
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
  function openInspection(view) {
    if (["metrics", "coverage"].includes(view.kind)) setModal(view);
    else setInspector(view);
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
  function select(next, fromSearch = false) {
    setInspector(null);
    setSelection(next);
    const files = selectionInfo(data, next).files;
    if (!allTree && (next.kind !== "file" || fromSearch))
      setExpanded(new Set(files.flatMap(parents)));
    if (fromSearch) {
      setExpanded((old) => new Set([...old, ...files.flatMap(parents)]));
      setQuery("");
      setSearchOpen(false);
      searchRef.current?.blur();
    }
  }
  useEffect(() => {
    if (selection?.kind === "file")
      panelRef.current
        ?.querySelector(`[data-tree-id="${CSS.escape(selection.id)}"]`)
        ?.scrollIntoView({ block: "nearest" });
  }, [selection, expanded]);
  function toggleTree() {
    setExpanded(
      new Set(
        (allTree ? info.files : inventoryFiles(data).map((f) => f.id)).flatMap(
          parents,
        ),
      ),
    );
    setAllTree(!allTree);
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
    <div className="app-shell">
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
        </div>
      </header>
      <ProjectOverview
        data={data}
        inspector={inspector}
        onOpen={openInspection}
      />
      <main className="board-layout" ref={architectureSplit.ref} style={{...architectureSplit.style,...(codeActive?{display:"none"}:{})}}>
        <section className="architecture-panel">
          <div className="panel-header">
            <div className="section-title">
              <div className="architecture-entry"><h2>系统架构</h2><button className="text-button browse-code-button" disabled={!data.project.root} title={data.project.root ? "浏览所选分组或文件" : "打开本地项目后浏览代码"} onClick={() => browseCode()}>浏览文件 <ChevronRight size={14}/></button></div>
            </div>
            <div className="panel-actions">
              {!data.coverage && data.diagnostics.length > 0 && (
                <button
                  className="text-button diagnostics-button"
                  onClick={() => setModal({ kind: "diagnostics" })}
                >
                  <Info size={14} />
                  {data.diagnostics.length} 项扫描说明
                </button>
              )}
              {data.project.root && (
                <button
                  className="icon-button"
                  aria-label="重新扫描项目"
                  title="重新扫描项目"
                  onClick={refresh}
                  disabled={busy}
                >
                  <RefreshCw size={15} className={busy ? "spin" : ""} />
                </button>
              )}
            </div>
          </div>
          <ReactFlowProvider>
            <ArchitectureGraph
              data={data}
              selection={selection}
              info={info}
              onSelect={select}
              onEnter={browseCode}
            />
          </ReactFlowProvider>
          <footer className="graph-footer">
            <span>
              <span className="legend-line" />
              静态代码引用
            </span>
            <span>{data.groups.length} 个分组</span>
          </footer>
        </section>
        <aside className="code-panel" ref={panelRef}>
          {inspector && (
            <InspectionPanel
              data={data}
              view={inspector}
              onBack={() => setInspector(null)}
              onOpen={openInspection}
              onSource={inspectSource}
            />
          )}
          <div
            className="code-tree-content"
            style={{ display: inspector ? "none" : "flex" }}
          >
            <div className="panel-header">
              <div className="section-title">
                <Link2 size={15} className="accent" />
                <h2>代码结构</h2>
              </div>
              <button className="text-button" onClick={toggleTree}>
                {allTree ? "返回关联路径" : "查看完整树"}
              </button>
            </div>
            <Tree
              data={data}
              expanded={expanded}
              setExpanded={setExpanded}
              linked={linked}
              focusId={focusId}
              onFile={(id) => select({ kind: "file", id })}
            />
            {selection?.kind === "group" && (
              <ModuleStatistics
                group={info.groups[0]}
              />
            )}
            {selection?.kind === "edge" && (
              <section className="selection-details" aria-live="polite">
                <div className="detail-heading">
                  <strong>代码引用</strong>
                  <span className="muted">{info.evidence.length} 处</span>
                </div>
                <div className="evidence-list">
                  {info.evidence.map((r, i) => (
                    <button
                      key={`${r.from}:${r.line}:${i}`}
                      className="evidence-row"
                      onClick={() =>
                        setModal({ kind: "source", id: r.from, line: r.line })
                      }
                    >
                      <FileCode2 size={14} />
                      <span>
                        <strong>
                          {r.from.split("/").at(-1)}:{r.line}
                        </strong>
                        <small title={r.to}>
                          引用 {r.to.split("/").at(-1)}
                        </small>
                      </span>
                      <ArrowUpRight size={14} />
                    </button>
                  ))}
                </div>
              </section>
            )}
            {selection?.kind === "file" && (
              <footer className="code-source-action">
                {!info.groups.length && (
                  <span className="muted">架构图中暂无对应模块</span>
                )}
                <button className="text-button" disabled={!data.project.root} onClick={() => browseCode()}>浏览文件关系 <ChevronRight size={14}/></button>
                <button
                  className="text-button"
                  disabled={!activeFile}
                  onClick={() =>
                    activeFile &&
                    setModal({ kind: "source", id: activeFile.id })
                  }
                >
                  {activeFile ? "打开源码" : "未提供源码预览"}
                  <ArrowUpRight size={14} />
                </button>
              </footer>
            )}
          </div>
        </aside>
        <PanelResize split={architectureSplit}/>
      </main>
      {codeEntry && <CodeBrowser data={data} entry={codeEntry} active={codeActive} onArchitecture={() => setCodeActive(false)}/>}
      <div className="app-status" role="status" style={codeActive ? {display:"none"} : undefined}>
        <Info size={13} />
        {notice ||
          (data.project.sample
            ? "交互示例。打开本地项目后查看实际源码结构。"
            : "代码引用可追溯；动态调用与运行时行为不在本次扫描范围内。")}
      </div>
      {modal?.kind === "project" && (
        <ProjectDialog
          current={data}
          onLoad={load}
          onClose={() => setModal(null)}
        />
      )}
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
