import React, { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ReactFlowProvider } from "@xyflow/react";
import { Copy, Plus, History, Send, Square, LoaderCircle, MessageSquare, GitBranch, RefreshCw, X, AlertCircle, Check, ChevronRight, PanelRightOpen } from "lucide-react";
import { Markdown } from "./ExplorationMarkdown.jsx";
import { AgentLogo } from "./AgentLogo.jsx";
import { ExplorationGraph } from "./ExplorationGraph.jsx";
import { SelectMenu } from "./SelectMenu.jsx";
import { ChatDrawer } from "./ChatDrawer.jsx";
import { agentNames, explorationApi as api, loadConversation, freshnessLabel, conversationRecords, toolRecordTitle } from "./exploration-api.js";
import { readingQuestion, readingPrompt, readingMessage } from "./reading-navigation.js";
import "./exploration.css";
import "./chat-drawer.css";

export function ExplorationWorkspace({ data, entry, active, drawer, SourceDialog, onSettings, onLocate, navigation, chatOnly = false, diagramContext, requestRef, onRunStart, onDiagrams, onExternalSource }) {
  const project = data.project.root, enabled = active || drawer.open;
  const [items, setItems] = useState([]), [selected, setSelected] = useState(null), [conversation, setConversation] = useState(null);
  const [sidebar, setSidebar] = useState(false), [agent, setAgent] = useState("codex"), [settings, setSettings] = useState(null), [probes, setProbes] = useState([]);
  const [text, setText] = useState(""), [sending, setSending] = useState(false), [loading, setLoading] = useState(false), [error, setError] = useState(""), [copied, setCopied] = useState(false);
  const [source, setSource] = useState(null), [sourceLoading, setSourceLoading] = useState(false), [summary, setSummary] = useState(false);
  const [context, setContext] = useState(null), [locating, setLocating] = useState(false), [locateError, setLocateError] = useState("");
  const drafts = useRef(new Map()), handledEntry = useRef(null), chatPositions = useRef(new Map()), configuredProject = useRef(null), selectionEpoch = useRef(0);
  const draftKey = (root, id) => `${root}\0${id || "new"}`;
  const bottom = useRef(null), chat = useRef(null), pinned = useRef(true), current = useRef({ selected, project }), sourceSerial = useRef(0), deliveredDiagrams = useRef(new Set()), initiatedRun = useRef(null);
  current.current = { selected, project };
  const running = conversation?.run?.status === "running", view = conversation?.view;
  const fresh = conversation?.freshness?.status || "unchecked";
  function editText(value) {
    setText(value);
    drafts.current.set(draftKey(project, selected), { text: value, context });
  }

  useEffect(() => {
    if (!enabled || !project) return;
    const controller = new AbortController();
    Promise.all([api("/api/settings", undefined, controller.signal), api("/api/agents", undefined, controller.signal)])
      .then(([config, detected]) => { setError(value => value?.connection ? "" : value); setSettings(config.settings); setProbes(detected.agents); if (configuredProject.current !== project) { setAgent(config.settings.defaultAgentId || "codex"); configuredProject.current = project; } })
      .catch(e => { if (e.name !== "AbortError") setError({ message: e.message, connection: true }); });
    return () => controller.abort();
  }, [enabled, project]);

  useEffect(() => {
    selectionEpoch.current++;
    sourceSerial.current++;
    setItems([]); setSelected(null); setConversation(null); setSource(null); setSourceLoading(false); setLocating(false); setSummary(false); setText(""); setContext(null); setError(""); setLoading(false);
    if (!project) return;
    let id = null;
    try { id = localStorage.getItem("strata-explore:" + project) || null; } catch { /* optional UI preference */ }
    setSelected(id);
    const draft = drafts.current.get(draftKey(project, id));
    setText(draft?.text || ""); setContext(draft?.context || null);
  }, [project]);

  useEffect(() => {
    if (!entry || entry.project !== project || handledEntry.current === entry.serial) return;
    handledEntry.current = entry.serial;
    choose(null);
    setContext(entry);
    setText(readingQuestion(entry));
    drafts.current.set(draftKey(project, null), { context: entry, text: readingQuestion(entry) });
  }, [entry?.serial, project]);

  useEffect(() => {
    if (!enabled || !project) return;
    let disposed = false, timer;
    const controller = new AbortController();
    async function refresh() {
      try {
        const result = await api("/api/explore/conversations", undefined, controller.signal);
        if (!disposed) { setItems(result.conversations); setError(value => value?.connection ? "" : value); }
      } catch (e) { if (!disposed && e.name !== "AbortError") setError({ message: e.message, connection: true }); }
      if (!disposed) timer = setTimeout(refresh, 4000);
    }
    refresh();
    return () => { disposed = true; controller.abort(); clearTimeout(timer); };
  }, [enabled, project]);

  useEffect(() => {
    if (!selected || !enabled) return;
    let disposed = false, timer;
    const controller = new AbortController();
    if (conversation?.id !== selected) setLoading(true);
    if (!chatOnly) api(`/api/explore/conversations/${selected}/check`, {}, controller.signal).catch(e => { if (!disposed && e.name !== "AbortError") setError({ message: e.message, connection: true }); });
    async function refresh() {
      try {
        const result = await loadConversation(selected, controller.signal);
        if (!disposed) {
          setConversation(result); setLoading(false); setError(value => value?.connection ? "" : value);
        }
      } catch (e) { if (!disposed && e.name !== "AbortError") { setError({ message: e.message, connection: true }); setLoading(false); } }
      if (!disposed) timer = setTimeout(refresh, 1200);
    }
    refresh();
    return () => { disposed = true; controller.abort(); clearTimeout(timer); };
  }, [selected, enabled, data.snapshot.id]);

  useEffect(() => {
    if (enabled && chat.current) {
      const position = chatPositions.current.get(draftKey(project, selected));
      if (position != null) chat.current.scrollTop = position;
    }
  }, [enabled, selected, conversation?.id]);

  const last = conversation?.history.messages.at(-1);
  const assistant = conversation?.history.messages.filter(m => m.role === "assistant").at(-1)?.content.text;
  useEffect(() => {
    // Scroll only the message list: a viewport drawer must never move the graph/page.
    if (pinned.current && enabled && drawer.open && chat.current && !sidebar) chat.current.scrollTop = chat.current.scrollHeight;
  }, [last?.seq, assistant, enabled, drawer.open, sidebar]);

  function choose(id) {
    selectionEpoch.current++;
    drafts.current.set(draftKey(project, selected), { text, context });
    const draft = drafts.current.get(draftKey(project, id));
    setSelected(id); setError(""); setText(draft?.text || ""); setContext(draft?.context || null); setSidebar(false); pinned.current = !chatPositions.current.has(draftKey(project, id));
    setConversation(null); setSource(null); setSourceLoading(false); setLocating(false); setSummary(false); setLocateError(""); setLoading(Boolean(id)); sourceSerial.current++;
    try { if (id) localStorage.setItem("strata-explore:" + project, id); else localStorage.removeItem("strata-explore:" + project); } catch { /* optional */ }
  }
  async function send(update = false, override) {
    const question = override || (update ? "请基于当前代码重新查询、更新这张阅读图，并说明主要变化。" : text.trim());
    if (!question || sending || running) return;
    const prompt = readingPrompt(question, !selected ? context : null);
    if (prompt.length > 12000) { setError("问题与代码范围合计最多 12000 字，请缩短问题后重试。"); return; }
    setSending(true); setError(""); onRunStart?.();
    const atProject = project, epoch = selectionEpoch.current;
    try {
      let id = selected;
      if (!id) {
        const created = await api("/api/explore/conversations", { agentId: agent, title: question.slice(0, 45) });
        id = created.id;
      }
      const started = await api(`/api/explore/conversations/${id}/messages`, { text: prompt, update, ...(diagramContext ? { diagramId: diagramContext.id, expectedRevision: diagramContext.expectedRevision } : {}) });
      initiatedRun.current = started.id;
      if (current.current.project !== atProject || selectionEpoch.current !== epoch) return;
      if (current.current.selected !== selected) return;
      drafts.current.delete(draftKey(project, selected));
      setText(""); setContext(null); pinned.current = true;
      if (id !== selected) {
        setSelected(id); setConversation(null); setSource(null); setSummary(false); setSidebar(false);
        try { localStorage.setItem("strata-explore:" + project, id); } catch { /* optional */ }
      }
      const result = await loadConversation(id);
      if (selectionEpoch.current === epoch && current.current.project === atProject && (current.current.selected === id || id !== selected)) setConversation(result);
      const list = await api("/api/explore/conversations");
      if (current.current.project === atProject) setItems(list.conversations);
    } catch (e) { if (current.current.project === atProject && selectionEpoch.current === epoch) setError(e.message); }
    finally { setSending(false); }
  }
  useEffect(() => {
    if (requestRef) requestRef.current = async ({question, update = false, prepare = false}) => {
      if (prepare) { editText(question); return; }
      return send(update, question);
    };
  });
  useEffect(() => {
    for (const message of conversation?.history.messages || []) {
      if (message.kind === 'diagrams' && message.run_id === initiatedRun.current && conversation.run?.status === 'completed' && !deliveredDiagrams.current.has(message.seq)) {
        deliveredDiagrams.current.add(message.seq);
        if (message.run_id === conversation.run?.id && conversation.run?.status === 'completed') onDiagrams?.(message.content.diagramIds);
      }
    }
  }, [conversation?.run?.id, conversation?.run?.status, conversation?.history.messages.length]);
  async function stop() {
    try { await api(`/api/explore/conversations/${selected}/cancel`, {}); }
    catch (e) { setError(e.message); }
  }
  const openSource = useCallback(async (node) => {
    const id = current.current.selected, snapshotId = node.snapshotId || conversation?.view?.snapshotId || conversation?.run?.snapshot_id;
    if (!id || !node.path || !snapshotId) return;
    if (chatOnly && onExternalSource) { onExternalSource(node, id, snapshotId); return; }
    const serial = ++sourceSerial.current, line = node.range?.start[0] || 1;
    setSourceLoading(true); setError("");
    try {
      const result = await api("/api/explore/read", { name: "read_snapshot_source", arguments: { id, snapshotId, path: node.path, startLine: node.startLine || Math.max(1, line - 35), endLine: node.startLine ? node.startLine + 299 : line + 200 } });
      if (serial !== sourceSerial.current || current.current.selected !== id) return;
      setSource({ file: { id: snapshotId + result.path, path: result.path, language: result.language, content: result.content, lineOffset: result.startLine - 1, endLine: result.endLine, totalLines: result.totalLines }, line, snapshotId, target: { ...node, snapshotId } });
      setLocateError("");
    } catch (e) { if (serial === sourceSerial.current) setError(e.message); }
    finally { if (serial === sourceSerial.current) setSourceLoading(false); }
  }, [conversation?.view?.snapshotId, conversation?.run?.snapshot_id]);

  async function locateSource() {
    if (!source || locating) return;
    const at = current.current, serial = sourceSerial.current;
    const isCurrent = () => current.current.project === at.project && current.current.selected === at.selected && sourceSerial.current === serial;
    setLocating(true); setLocateError("");
    try { if (await onLocate(source.target, isCurrent)) setSource(null); }
    catch (e) { if (isCurrent() && e.name !== "AbortError") setLocateError(e.message); }
    finally { if (isCurrent()) setLocating(false); }
  }

  async function copyId() {
    try { await navigator.clipboard.writeText(selected); setCopied(true); setTimeout(() => setCopied(false), 1800); }
    catch { setError("无法自动复制，请选中会话 ID 手动复制：" + selected); }
  }
  const selectedAgent = conversation?.agent_id || agent, detected = probes.find(p => p.id === selectedAgent);
  const messages = conversation?.history.messages || [];
  const sourceDialog = source && <SourceDialog file={source.file} line={source.line} onClose={() => { sourceSerial.current++; setSource(null); setLocating(false); setSourceLoading(false); }} onLocate={locateSource} locating={locating} locateError={locateError} onPage={line => openSource({...source.target, startLine:line})}/>;
  return <section className={`exploration-workspace ${chatOnly ? "uml-chat-only" : ""}`} style={active ? undefined : { display: "none" }} aria-label="功能解读">
    <div className="explore-body">
      <div className="explore-canvas">
        <div className="explore-canvas-bar workspace-canvas-toolbar">{navigation}<span className="explore-canvas-title" title={view?.title || "功能阅读图"}><GitBranch size={15}/><span>{view?.title || "功能阅读图"}</span></span><div className="explore-canvas-actions">{view && <button className="text-button" onClick={() => setSummary(v => !v)}>{summary ? "收起图说明" : "图说明"}</button>}{!drawer.open && <button className="text-button explore-open-chat" data-chat-opener onClick={() => drawer.setOpen(true)}><PanelRightOpen size={16}/>展开会话</button>}</div></div>
        {view ? <>
          <div className={`explore-freshness is-${fresh}`} role="status"><span>{["checking", "unchecked"].includes(fresh) ? <LoaderCircle size={14} className={fresh === "checking" ? "spin" : ""}/> : fresh === "current" ? <Check size={14}/> : <AlertCircle size={14}/>} {freshnessLabel(fresh)}</span><small title={view.snapshotId}>源码快照 {view.snapshotId.slice(0, 10)}</small>
            {["stale", "error"].includes(fresh) && <button className="text-button" onClick={() => send(true)} disabled={running || sending}><RefreshCw size={13}/>让 Agent 更新</button>}
            {["unchecked", "error"].includes(fresh) && <button className="text-button" onClick={() => api(`/api/explore/conversations/${selected}/check`, {}).catch(e => setError(e.message))}>检查变化</button>}
          </div>
          <div className="explore-graph"><ReactFlowProvider><ExplorationGraph view={view} onSource={openSource}/></ReactFlowProvider></div>
          {summary && <div className="explore-view-summary"><Markdown text={view.explanation || "这张图还没有单独的说明，可在右侧追问。"} onSource={openSource}/></div>}
          <footer><span><i/>静态关系 <i className="uncertain"/>候选 / 未解析</span><span>{view.view === "logic" ? "单函数结构简图 · 非完整控制流" : "点击节点或连线查看快照源码"}</span></footer>
        </> : <div className="explore-empty"><span className="explore-empty-icon"><GitBranch size={30}/></span><h2>{running ? "正在构造阅读图" : "把一个功能，展开成可阅读的代码图"}</h2><p>{running ? "Agent 正在查询源码和调用依据，完成后图会保存在这里。" : "从入口追到关键函数，再沿着源码依据读懂实现。"}</p><div className="explore-empty-flow"><span>定位入口</span><i>→</i><span>查证调用</span><i>→</i><span>组织阅读图</span></div><small>Python / TS 静态分析 · 源码快照 · 自动保存</small></div>}
        {sourceLoading && <div className="explore-loading"><LoaderCircle className="spin" size={17}/>正在读取快照源码</div>}
        {source && (active ? <div className="explore-source-host">{sourceDialog}</div> : createPortal(sourceDialog, document.body))}
      </div>
      <ChatDrawer active={true} drawer={drawer} label={`${agentNames[selectedAgent]} 会话`} onClose={() => drawer.setOpen(false)}>
        <header><AgentLogo id={selectedAgent} size={28}/><div><strong>{agentNames[selectedAgent]}</strong><small>{settings?.agents[selectedAgent]?.model || "使用 CLI 默认模型"}</small></div><button className="icon-button explore-history-toggle" title="阅读历史" aria-label="阅读历史" aria-expanded={sidebar} aria-controls={sidebar ? "explore-history-list" : undefined} onClick={() => setSidebar(v => !v)}><History size={17}/></button><button className="drawer-new" onClick={() => choose(null)}><Plus size={15}/>新主题</button><button className="icon-button" data-drawer-close aria-label="收起会话" title="收起会话（Esc）" onClick={() => drawer.setOpen(false)}><X size={18}/></button></header>
        <div className="drawer-topic"><strong title={conversation?.title || "从一个功能，开始读代码"}>{conversation?.title || "从一个功能，开始读代码"}</strong>{selected && <button className="text-button explore-copy" title={selected} onClick={copyId}>{copied ? <Check size={14}/> : <Copy size={14}/>} {copied ? "已复制" : "复制会话 ID"}</button>}</div>
        {sidebar && <section className="explore-history" id="explore-history-list" aria-label="此项目的阅读历史"><header><strong>阅读历史</strong><button className="icon-button" aria-label="关闭阅读历史" onClick={() => setSidebar(false)}><X size={15}/></button></header>
          <button className="explore-new" onClick={() => choose(null)}><Plus size={15}/>新建阅读主题</button>
          {items.map(item => <button key={item.id} className={`explore-history-item ${selected === item.id ? "is-active" : ""}`} aria-current={selected === item.id ? "true" : undefined} onClick={() => choose(item.id)}><AgentLogo id={item.agent_id}/><span><strong>{item.title}</strong><small>{agentNames[item.agent_id]} · {new Date(item.updated_at).toLocaleDateString()}</small></span></button>)}
          {!items.length && <p>阅读主题和阅读图会自动保存在这里。</p>}
        </section>}
        <div className="explore-messages" ref={chat} style={sidebar ? {display:"none"} : undefined} onScroll={() => { const el = chat.current; pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 90; chatPositions.current.set(draftKey(project, selected), el.scrollTop); }}>
          {loading && <p className="explore-chat-hint"><LoaderCircle size={14} className="spin"/>正在读取阅读主题</p>}
          {!messages.length && !loading && <div className="explore-chat-welcome"><MessageSquare size={23}/><h3>你想读懂哪一段实现？</h3><p>可以给出功能名称、函数名或文件路径。Agent 会先查证，再构造图。</p>{["帮我找到项目的主要入口，并画出关键调用关系", "画出这个功能的活动图、时序图和模块组件图"].map(prompt => <button key={prompt} onClick={() => editText(prompt)}>{prompt}</button>)}</div>}
          {conversationRecords(messages).map(message => {
            const content = message.content, snapshotId = message.snapshot_id;
            const sourceFromMessage = node => { if (snapshotId) openSource({ ...node, snapshotId }); };
            if (message.kind === "tool_call") {
              const title = toolRecordTitle(content), failed = Boolean(message.result?.error), pending = !message.result && running && message.run_id === conversation?.run?.id;
              return <details key={message.seq} className={`explore-tool explore-tool-record ${failed ? "is-error" : ""}`}><summary>
                <ChevronRight className="explore-disclosure" size={13}/><span>{title.label}</span>{title.scope && <small title={title.scope}>{title.scope}</small>}
                {failed ? <span className="explore-tool-state">失败</span> : pending ? <LoaderCircle size={12} className="spin explore-tool-state"/> : !message.result ? <span className="explore-tool-state">已中断</span> : null}
              </summary><div className="explore-tool-detail"><code>{content.name}</code><strong>查询参数</strong><pre>{JSON.stringify(content.arguments, null, 2)}</pre>
                {message.result && <><strong>{failed ? "错误说明" : "返回结果"}</strong><pre>{message.result.error || JSON.stringify(message.result.result, null, 2)}</pre></>}
              </div></details>;
            }
            if (message.kind === "tool_result") return <details key={message.seq} className={`explore-tool ${content.error ? "is-error" : ""}`}><summary>{content.error ? "调用失败" : "已返回依据"} · {content.name}</summary><pre>{content.error || JSON.stringify(content.result, null, 2)}</pre></details>;
            if (message.kind === "diagrams") return <p key={message.seq} className="explore-run-status">已保存 {content.diagramIds.length} 张项目 UML 图</p>;
            if (message.kind === "status") return <p key={message.seq} className={`explore-run-status is-${content.status}`}>{content.text}</p>;
            if (message.kind === "error_details") return <details key={message.seq} className="explore-tool is-error"><summary>运行诊断</summary><pre>{content.text}</pre></details>;
            const display = message.role === "user" ? readingMessage(content.text || "") : null;
            return <article key={message.seq} className={`explore-message is-${message.role}`}><small>{message.role === "user" ? "你" : agentNames[selectedAgent]}</small>{display ? <><p>{display.text}</p>{display.context && <div className="explore-message-scope">{display.context.kind === "group" ? "模块" : display.context.kind === "file" ? "文件" : "函数"} · {display.context.name}<small>{display.context.path || `${display.context.fileCount || display.context.files?.length || 0} 个文件`}</small></div>}</> : <Markdown text={content.text || ""} onSource={sourceFromMessage}/>}</article>;
          })}
          {running && <p className="explore-chat-hint"><LoaderCircle className="spin" size={14}/>正在阅读源码与组织视图…</p>}<div ref={bottom}/>
        </div>
        {error && !sidebar && <div className="explore-error" role="alert">{typeof error === 'string' ? error : error.message}</div>}
        <form className="explore-composer" style={sidebar ? {display:"none"} : undefined} onSubmit={e => { e.preventDefault(); send(); }}>
          {context && !selected && <div className="explore-code-context"><strong>{context.kind === "group" ? "模块" : context.kind === "file" ? "文件" : "函数"} · {context.name}</strong><small>{context.path || `${context.files?.length || 0} 个文件`}{context.range ? `:${context.range.start[0]}` : ""}</small><small>来源快照 {context.snapshotId.slice(0, 8)} · 发送时重新查询</small></div>}
          {diagramContext ? <div className="drawer-view-context" title={diagramContext.title}><GitBranch size={13}/>已关联 {diagramContext.title}</div> : view && !chatOnly && <div className="drawer-view-context" title={view.title}><GitBranch size={13}/>已关联当前阅读图</div>}
          {!selected && <div className="explore-agent-select"><span>本会话 Agent</span><SelectMenu label="本会话 Agent" value={agent} disabled={sending || !drawer.open} onChange={setAgent} className="explore-agent-trigger" popupClassName="explore-agent-menu" align="end" options={Object.entries(agentNames).map(([value, label]) => ({value, label, icon:<AgentLogo id={value} size={17}/>}))}/></div>}
          {!selected && detected?.status !== "detected" && <small className="explore-config-hint">{detected?.message || "请先配置本地 Agent CLI"} <button type="button" className="text-button" onClick={onSettings}>配置 Agent</button></small>}
          <textarea value={text} onChange={e => editText(e.target.value)} maxLength={12000} rows={3} placeholder={running ? "可先写好下一个问题" : selected ? "继续追问，或选中图中的节点…" : "描述功能，或选择代码后解读…"} aria-label="向 Agent 提问" onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }}/>
          <footer><span>只读分析 · {selected ? "沿用图的源码快照" : "保存会话与源码快照"}</span>{running ? <button type="button" onClick={stop} className="explore-send"><Square size={13}/>停止</button> : <button type="submit" disabled={!text.trim() || sending || !project || loading} className="explore-send">{sending ? <LoaderCircle size={15} className="spin"/> : <Send size={15}/>}发送</button>}</footer>
        </form>
      </ChatDrawer>
    </div>
  </section>;
}
