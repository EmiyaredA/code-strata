import React, { useEffect, useRef, useState } from "react";
import { Check, CheckCircle2, CircleAlert, LoaderCircle, RefreshCw, Terminal, XCircle } from "lucide-react";
import "./agent-settings.css";
import { AgentLogo } from "./AgentLogo.jsx";
import { ModelPicker } from "./ModelPicker.jsx";
import { SelectMenu } from "./SelectMenu.jsx";
import { catalogModel, inheritedParameter, parameterSelection } from "./agent-values.js";
import { apiFetch } from './api-fetch.js';

const names = { codex: "Codex", opencode: "OpenCode", dsh: "DeepSeek Harness", claude: "Claude Code", pi: "Pi" };
const ids = Object.keys(names);
const empty = () => ({ version: 1, defaultAgentId: null,
  agents: Object.fromEntries(ids.map(id => [id, { executablePath: "", model: "" }])) });
const statusName = { detected: "已检测到", unavailable: "无法运行", not_found: "未找到" };
const parameterNames = { reasoningEffort: "推理强度", serviceTier: "速度档位", variant: "模型变体", thinking: "思考强度", fastMode: "快速模式" };

async function api(path, body, keepalive = false) {
  const response = await apiFetch(path, {
    method: body === undefined ? "GET" : "POST", keepalive,
    headers: { "X-Architecture-Token": document.querySelector('meta[name="architecture-token"]')?.content || "",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "请求失败，请重试");
  return result;
}

export function AgentSettings({ Dialog, onClose }) {
  const [draft, setDraft] = useState(empty);
  const [saved, setSaved] = useState("");
  const [selected, setSelected] = useState("codex");
  const [agents, setAgents] = useState([]);
  const [probePaths, setProbePaths] = useState({});
  const [loading, setLoading] = useState(true);
  const [detecting, setDetecting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [test, setTest] = useState(null);
  const [starting, setStarting] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [catalog, setCatalog] = useState(null);
  const lifecycle = useRef({ mounted: false, id: null, started: 0 });
  const running = starting || test?.status === "running";
  const locked = loading || saving || running;
  const config = draft.agents[selected];
  const agent = agents.find(item => item.id === selected);
  const stale = probePaths[selected] !== config.executablePath;
  const dirty = JSON.stringify(draft) !== saved;
  const catalogKey = JSON.stringify([selected, config.executablePath, selected !== "codex" ? config.model : ""]);
  const currentCatalog = catalog?.key === catalogKey ? catalog : null;
  const selectedModel = catalogModel(currentCatalog, config.model);
  const descriptors = (selected === "dsh" || selected === "pi" || (selected === "claude" && !config.model) ? currentCatalog?.parameters : selectedModel?.parameters) || [];
  const parameters = config.parameters || {};
  const fields = [...descriptors, ...Object.keys(parameters).filter(key => !descriptors.some(item => item.key === key))
    .map(key => ({ key, label: parameterNames[key], options: [] }))];
  const invalidParameters = Object.entries(parameters).some(([key, value]) => !descriptors.some(item => item.key === key && item.options.some(option => option.value === value)));

  useEffect(() => {
    const life = { mounted: true, id: null, started: 0 };
    lifecycle.current = life;
    async function load() {
      try {
        const result = await api("/api/settings");
        if (!life.mounted) return;
        setDraft(result.settings);
        setSaved(JSON.stringify(result.settings));
        if (result.settings.defaultAgentId) setSelected(result.settings.defaultAgentId);
        if (result.error) setError(result.error);
        setLoading(false);
        setDetecting(true);
        const detected = await api("/api/agents");
        if (!life.mounted) return;
        setAgents(detected.agents);
        setProbePaths(Object.fromEntries(ids.map(id => [id, result.settings.agents[id].executablePath])));
      } catch (err) {
        if (life.mounted) setError(err.message);
      } finally {
        if (life.mounted) { setLoading(false); setDetecting(false); }
      }
    }
    load();
    return () => {
      life.mounted = false;
      if (life.id) api(`/api/agents/tests/${life.id}/cancel`, {}, true).catch(() => {});
    };
  }, []);

  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - lifecycle.current.started) / 1000)), 500);
    return () => clearInterval(timer);
  }, [running]);

  function edit(key, value) {
    if (config[key] === value) return;
    setDraft(current => {
      const next = { ...current.agents[selected], [key]: value };
      if (key === "model") delete next.parameters;
      return { ...current, agents: { ...current.agents, [selected]: next } };
    });
    setTest(null); setNotice(key === "model" && Object.keys(parameters).length ? "已切换模型，正在读取对应参数" : ""); setError("");
  }

  function editParameter(key, value) {
    if ((parameters[key] || "") === value) return;
    setDraft(current => {
      const next = { ...current.agents[selected] }, values = { ...next.parameters };
      if (value) values[key] = value; else delete values[key];
      if (Object.keys(values).length) next.parameters = values; else delete next.parameters;
      return { ...current, agents: { ...current.agents, [selected]: next } };
    });
    setTest(null); setNotice(""); setError("");
  }

  async function detect() {
    setDetecting(true); setError(""); setNotice("");
    const configs = draft.agents;
    try {
      const result = await api("/api/agents/detect", { agents: configs });
      if (!lifecycle.current.mounted) return;
      setAgents(result.agents);
      setProbePaths(Object.fromEntries(ids.map(id => [id, configs[id].executablePath])));
    } catch (err) { if (lifecycle.current.mounted) setError(err.message); }
    finally { if (lifecycle.current.mounted) setDetecting(false); }
  }

  async function save() {
    setSaving(true); setError(""); setNotice("");
    try {
      const result = await api("/api/settings", draft);
      if (!lifecycle.current.mounted) return;
      setDraft(result.settings); setSaved(JSON.stringify(result.settings));
      setNotice("设置已保存");
    } catch (err) { if (lifecycle.current.mounted) setError(err.message); }
    finally { if (lifecycle.current.mounted) setSaving(false); }
  }

  async function runTest() {
    if (running) return;
    const life = lifecycle.current;
    life.started = Date.now();
    setStarting(true); setElapsed(0); setTest(null); setError(""); setNotice("");
    try {
      let result = await api("/api/agents/tests", { agentId: selected, config });
      life.id = result.id;
      if (!life.mounted) {
        await api(`/api/agents/tests/${result.id}/cancel`, {}, true);
        return;
      }
      setTest(result); setStarting(false);
      while (result.status === "running" && life.mounted) {
        await new Promise(resolve => setTimeout(resolve, 650));
        if (!life.mounted) return;
        result = await api(`/api/agents/tests/${result.id}`);
        if (life.mounted) setTest(result);
      }
      life.id = null;
    } catch (err) {
      if (life.id) api(`/api/agents/tests/${life.id}/cancel`, {}, true).catch(() => {});
      life.id = null;
      if (life.mounted) { setError(err.message); setTest(null); }
    } finally { if (life.mounted) setStarting(false); }
  }

  async function cancelTest() {
    if (!lifecycle.current.id) return;
    try { await api(`/api/agents/tests/${lifecycle.current.id}/cancel`, {}); }
    catch (err) { setError(err.message); }
  }

  const testIcon = running ? <LoaderCircle size={16} className="spin" /> :
    test?.status === "success" ? <CheckCircle2 size={16} /> : <XCircle size={16} />;
  return <Dialog title="设置" subtitle="本地 Code Agent" wide className="dialog-agent-settings" onClose={onClose}>
    <div className="agent-settings-body">
      <nav className="agent-settings-list" aria-label="本地 Code Agent">
        <div className="agent-list-label">CODE AGENTS</div>
        {ids.map(id => {
          const item = agents.find(row => row.id === id);
          const fresh = probePaths[id] === draft.agents[id].executablePath;
          return <button type="button" key={id} className={id === selected ? "is-selected" : ""}
            aria-pressed={id === selected} disabled={running} onClick={() => { setSelected(id); setTest(null); setNotice(""); }}>
            <span className="agent-list-top"><AgentLogo id={id} /><strong>{names[id]}</strong>
              {draft.defaultAgentId === id && <span className="agent-default-tag">默认</span>}</span>
            <span className="agent-list-status"><i className={`agent-status-dot ${fresh ? item?.status || "" : ""}`} />
              {detecting ? "检测中…" : fresh && item ? statusName[item.status] : "尚未检测"}</span>
          </button>;
        })}
        <button type="button" className="agent-rescan" disabled={locked || detecting} onClick={detect}>
          <RefreshCw size={13} className={detecting ? "spin" : ""} />{detecting ? "正在检测" : "重新检测"}
        </button>
      </nav>
      <div className="agent-settings-content">
        <div className="agent-config-heading"><div className="agent-heading-title"><AgentLogo id={selected} size={22} /><h2>{names[selected]}</h2></div>
          <button type="button" className="text-button agent-set-default" disabled={locked || draft.defaultAgentId === selected}
            onClick={() => { setDraft(current => ({ ...current, defaultAgentId: selected })); setNotice(""); }}>
            {draft.defaultAgentId === selected ? <><Check size={13} />默认 Agent</> : "设为默认"}
          </button>
        </div>
        {loading ? <p className="agent-loading" role="status"><LoaderCircle size={15} className="spin" />正在读取设置…</p> : <>
          <div className="agent-detected-meta">
            <span>执行路径</span><code title={!stale ? agent?.executablePath : undefined}>
              {stale ? "尚未检测此路径" : agent?.executablePath || (detecting ? "检测中…" : "未找到可执行文件")}</code>
            <span>版本</span><span title={agent?.version || undefined}>{!stale && agent?.version || "—"}</span>
          </div>
          {!stale && agent?.status !== "detected" && agent?.message && <p className="agent-inline-note"><CircleAlert size={14} />{agent.message}</p>}
          <label className="agent-config-field" htmlFor="agent-executable">可执行文件路径
            <input id="agent-executable" type="text" spellCheck="false" autoComplete="off" value={config.executablePath}
              disabled={locked} placeholder="留空，自动检测本地 CLI" onChange={e => edit("executablePath", e.target.value)} />
            <small>可填写绝对路径；留空使用自动检测。</small>
          </label>
          <ModelPicker key={selected} agentId={selected} executablePath={config.executablePath} value={config.model}
            disabled={locked} enabled={!loading} onChange={value => edit("model", value)}
            onCatalog={setCatalog}
            requestModels={force => api("/api/agents/models", { agentId: selected, config, force })} />
          {fields.length > 0 && <div className="agent-parameters" aria-label="模型参数">
            {fields.map(field => {
              const value = parameters[field.key] || "";
              const inherited = inheritedParameter(currentCatalog, config.model, field.key);
              const selection = parameterSelection(field, value, inherited);
              return <div key={field.key} className="agent-parameter-field" title={!value && inherited ? `来源：${inherited.source}` : undefined}>
                <label>{field.label}<span>{value ? "已设置" : inherited ? inherited.source : "未读取"}</span></label>
                <SelectMenu label={field.label} value={selection.value} disabled={locked}
                  options={selection.options}
                  onChange={value => editParameter(field.key, value)} />
                {field.hint && <small>{field.hint}</small>}
              </div>;
            })}
          </div>}
          {invalidParameters && <p className="agent-parameter-note" role="status">当前参数尚未确认受支持；请等待获取、刷新模型列表或重新选择参数后再测试。</p>}
          {!fields.length && currentCatalog?.status === "ready" && <p className="agent-parameter-note">
            {currentCatalog.parameterMessage || currentCatalog.defaultsMessage || "CLI 未提供此模型的额外参数。"}</p>}
          <div className="agent-test-actions">
            <button type="button" className="button" disabled={loading || saving || detecting || running || invalidParameters} onClick={runTest}>
              {running ? <LoaderCircle size={14} className="spin" /> : <Terminal size={14} />}{running ? "正在测试" : "测试连接"}
            </button>
            {running ? <><span role="status">{elapsed}s</span><button type="button" className="text-button" onClick={cancelTest} disabled={starting}>取消测试</button></> :
              <small>会发送一条模型请求</small>}
          </div>
          {test && <div className={`agent-test-result ${test.status}`} role="status">
            <div className="agent-test-summary">{testIcon}<strong>{test.message}</strong>
              {test.status !== "running" && <span>{(test.durationMs / 1000).toFixed(1)}s</span>}</div>
            {test.response && <code className="agent-test-response">{test.response}</code>}
            {test.status !== "running" && (test.executablePath || Object.values(test.details || {}).some(Boolean)) &&
              <details><summary>测试详情</summary>
                {test.executablePath && <p>执行路径：<code>{test.executablePath}</code></p>}
                {test.kind && <p>类型：{test.kind}</p>}
                {Object.entries(test.details || {}).filter(([, value]) => value).map(([name, value]) =>
                  <div key={name}><span>{name}</span><pre>{value}</pre></div>)}
              </details>}
          </div>}
        </>}
        {error && <p className="agent-settings-error" role="alert"><CircleAlert size={14} />{error}</p>}
      </div>
    </div>
    <footer className="agent-settings-footer"><span role="status">{notice || (dirty && !loading ? "有未保存的修改" : "设置对当前用户的所有项目生效")}</span>
      <button type="button" className="button" disabled={locked || !dirty} onClick={save}>
        {saving ? <LoaderCircle size={14} className="spin" /> : <Check size={14} />}保存设置
      </button>
    </footer>
  </Dialog>;
}
