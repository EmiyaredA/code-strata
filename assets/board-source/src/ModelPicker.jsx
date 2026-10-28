import React, { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown, Copy, LoaderCircle, Pencil, RefreshCw, Search } from "lucide-react";
import { catalogModel, resolvedModel } from "./agent-values.js";

export function ModelPicker({ agentId, executablePath, value, disabled, enabled, requestModels, onChange, onCatalog }) {
  const id = useId();
  const anchor = useRef(null), trigger = useRef(null), popup = useRef(null), search = useRef(null), manualInput = useRef(null);
  const sequence = useRef(0), alive = useRef(true), request = useRef(requestModels);
  request.current = requestModels;
  const report = useRef(onCatalog);
  report.current = onCatalog;
  const [catalog, setCatalog] = useState(null), [fetching, setFetching] = useState(false);
  const [open, setOpen] = useState(false), [query, setQuery] = useState(""), [active, setActive] = useState(0);
  const [position, setPosition] = useState(null), [manualChoice, setManualChoice] = useState(false), [copied, setCopied] = useState(false);
  const key = JSON.stringify([agentId, executablePath, agentId !== "codex" ? value : ""]);
  const current = catalog?.key === key ? catalog : null;
  const nativeId = current?.defaults?.model?.value;
  const directory = current?.models || [];
  const models = nativeId && !directory.some(model => model.id === nativeId || model.resolvedId === nativeId)
    ? [{ id: nativeId, label: nativeId }, ...directory] : directory;
  const effectiveId = resolvedModel(current, value);
  const selected = catalogModel(current, value);
  const nativeModel = catalogModel(current, "");
  const nativeLabel = nativeId ? nativeModel?.label || nativeId : fetching ? "正在读取本机模型…" : "未能读取本机模型，请选择";
  const displayLabel = value ? selected?.label || value : nativeLabel;
  const selectedId = selected?.id || effectiveId;
  const manual = manualChoice || Boolean(value && !selected);
  const terms = query.trim().toLocaleLowerCase();
  const filtered = models.filter(model => `${model.label} ${model.id} ${model.resolvedId || ""} ${model.provider || ""}`.toLocaleLowerCase().includes(terms));
  const choices = [...filtered.slice(0, 100).map(model => ({ ...model, kind: "model" })),
    { kind: "manual", id: "", label: "手动输入模型 ID" }];

  useEffect(() => { report.current?.(current); }, [current]);

  async function fetchCatalog(force) {
    const serial = ++sequence.current;
    setFetching(true);
    if (!force) setCatalog(null);
    try {
      const result = await request.current(force);
      if (alive.current && serial === sequence.current) setCatalog({ ...result, key });
    } catch (error) {
      if (alive.current && serial === sequence.current) setCatalog({ key, models: [], status: "error", message: error.message });
    } finally {
      if (alive.current && serial === sequence.current) setFetching(false);
    }
  }

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; sequence.current++; };
  }, []);
  useEffect(() => {
    sequence.current++;
    setCatalog(null); setOpen(false); setQuery(""); setManualChoice(false); setCopied(false);
    setFetching(Boolean(enabled));
    if (!enabled) return;
    const timer = setTimeout(() => fetchCatalog(false), 500);
    return () => { clearTimeout(timer); sequence.current++; };
  }, [key, enabled]);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1800);
    return () => clearTimeout(timer);
  }, [copied]);
  useEffect(() => { setCopied(false); }, [value]);
  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  function show() {
    setQuery("");
    const selectedIndex = models.findIndex(model => model.id === selectedId);
    setActive(selectedIndex >= 0 && selectedIndex < 100 ? selectedIndex : 0);
    setOpen(true);
  }
  function choose(option) {
    setOpen(false);
    if (option.kind === "manual") {
      setManualChoice(true);
      requestAnimationFrame(() => manualInput.current?.focus());
    } else {
      setManualChoice(false);
      if (selectedId !== option.id) onChange(option.id);
      trigger.current?.focus();
    }
  }
  useLayoutEffect(() => {
    if (!open) return;
    function place() {
      const rect = anchor.current.getBoundingClientRect();
      const rowsHeight = choices.reduce((height, option) => height +
        (option.kind === "model" && option.label !== option.id ? 52 : 34), 0);
      const hasNote = !filtered.length || filtered.length > 100 || fetching;
      const desired = Math.min(360, innerHeight - 24, 52 + rowsHeight + (hasNote ? 30 : 0));
      const above = rect.top - 12, below = innerHeight - rect.bottom - 12;
      const upward = below < desired && above > below;
      const height = Math.min(desired, Math.max(120, upward ? above : below));
      const width = Math.min(Math.max(300, rect.width), innerWidth - 24);
      setPosition({ left: Math.max(12, Math.min(rect.left, innerWidth - width - 12)), width,
        top: upward ? Math.max(12, rect.top - height - 5) : Math.min(rect.bottom + 5, innerHeight - height - 12), height });
    }
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => { window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); };
  }, [open, choices.length, fetching, filtered.length]);
  useEffect(() => {
    if (open && position) search.current?.focus();
  }, [open, Boolean(position)]);
  useEffect(() => {
    if (!open) return;
    function outside(event) {
      if (!anchor.current?.contains(event.target) && !popup.current?.contains(event.target)) setOpen(false);
    }
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);
  useEffect(() => {
    if (active >= choices.length) setActive(choices.length - 1);
    if (open) popup.current?.querySelector(`[id="${CSS.escape(`${id}-option-${active}`)}"]`)?.scrollIntoView({ block: "nearest" });
  }, [open, active, choices.length, id, Boolean(position)]);

  function keyboard(event) {
    if (event.key === "Escape" && open) {
      event.preventDefault(); event.stopPropagation(); setOpen(false); trigger.current?.focus();
    } else if (event.key === "Tab" && open) {
      setOpen(false); trigger.current?.focus();
    } else if (["ArrowDown", "ArrowUp"].includes(event.key)) {
      event.preventDefault();
      if (!open) show();
      else setActive(index => (index + (event.key === "ArrowDown" ? 1 : -1) + choices.length) % choices.length);
    } else if (event.key === "Enter" && open) {
      event.preventDefault(); choose(choices[active] || choices[0]);
    }
  }
  async function copyId() {
    try { await navigator.clipboard.writeText(effectiveId); setCopied(true); }
    catch { setCopied(false); }
  }

  return <div className="agent-config-field agent-model-field">
    <div className="agent-model-label"><label id={`${id}-label`} htmlFor={manual ? `${id}-manual` : `${id}-trigger`}>模型 <span>{value ? "已设置" : nativeId ? "本机配置" : "未读取"}</span></label>
      <button type="button" className="text-button" aria-label="刷新模型列表" disabled={disabled || !enabled || fetching}
        onClick={() => fetchCatalog(true)}><RefreshCw size={12} className={fetching ? "spin" : ""} />{fetching ? "获取中" : "刷新"}</button>
    </div>
    <div className={`agent-model-control ${manual ? "is-manual" : ""}`} ref={anchor}>
      {manual && <input ref={manualInput} id={`${id}-manual`} aria-label="手动输入模型 ID" value={value} disabled={disabled}
        spellCheck="false" autoComplete="off" placeholder="输入 CLI 支持的模型 ID" onChange={event => { setManualChoice(true); onChange(event.target.value); }} />}
      <button ref={trigger} id={`${id}-trigger`} type="button" role="combobox" aria-label="选择模型"
        aria-expanded={open} aria-controls={open ? `${id}-list` : undefined} aria-haspopup="listbox"
        disabled={disabled} onClick={() => open ? setOpen(false) : show()} onKeyDown={keyboard}
        title={manual ? "从模型列表选择" : displayLabel}>
        {!manual && <span>{displayLabel}</span>}
        <ChevronDown size={14} />
      </button>
    </div>
    {effectiveId && <div className="agent-model-id"><span>ID</span><code>{effectiveId}</code>
      <button type="button" className="text-button" aria-label="复制模型 ID" onClick={copyId} title={copied ? "已复制" : "复制 ID"}>
        {copied ? <Check size={12} /> : <Copy size={12} />}{copied ? "已复制" : "复制"}</button></div>}
    <small className={current && !["ready", "empty"].includes(current.status) ? "agent-model-warning" : ""} role="status"
      title={current?.source ? `来源：${current.source}${current.cached ? " · 已缓存" : ""}` : undefined}>
      {fetching ? "正在读取 CLI 模型目录，不发送生成请求…" : current?.status === "ready" ?
        `${models.length} 个模型 · 来自 CLI，连接状态以测试结果为准` : current?.message || "可从列表选择模型，也可手动输入完整 ID。"}
    </small>
    {open && position && createPortal(<div ref={popup} className="agent-model-popup" style={position} onKeyDown={keyboard}>
      <div className="agent-model-search"><Search size={14} /><input ref={search} role="combobox" aria-label="搜索模型"
        aria-expanded="true" aria-controls={`${id}-list`} aria-autocomplete="list" aria-activedescendant={`${id}-option-${active}`}
        placeholder="搜索名称、ID 或提供商" value={query} onChange={event => { setQuery(event.target.value); setActive(0); }} />
        {fetching && <LoaderCircle size={13} className="spin" />}</div>
      <div className="agent-model-options" role="listbox" id={`${id}-list`} aria-label="模型列表">
        {choices.map((option, index) => <div key={`${option.kind}:${option.id}`} id={`${id}-option-${index}`}
          role="option" aria-selected={option.kind !== "manual" && option.id === selectedId}
          className={`${active === index ? "is-active" : ""} ${option.kind !== "model" ? "is-action" : ""}`}
          onMouseDown={event => event.preventDefault()} onPointerMove={() => setActive(index)} onClick={() => choose(option)}>
          {option.kind === "manual" && <Pencil size={13} />}
          <div><strong>{option.label}</strong>{option.kind === "model" && option.label !== option.id && <code>{option.id}</code>}</div>
          {option.kind !== "manual" && option.id === selectedId && <Check size={14} />}
        </div>)}
      </div>
      {(!filtered.length || filtered.length > 100 || fetching) && <div className="agent-model-list-note">
        {fetching ? "正在获取模型…" : filtered.length > 100 ? `显示前 100 项，共 ${filtered.length} 项；继续搜索缩小范围` : terms ? "没有匹配模型，可手动输入 ID" : "暂无可选模型，可手动输入 ID"}
      </div>}
    </div>, trigger.current?.closest('[role="dialog"]') || document.body)}
  </div>;
}
