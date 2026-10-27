import React, { useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, ChevronRight, CircleAlert, FileCode2, Folder, Search, X } from "lucide-react";
import { SelectMenu } from "./SelectMenu.jsx";
import {
  aggregateFiles, directoryRows, fileMedian, isCounted, languageName, languageRows,
  needsAttention, parserSummary, percent, ranked, ratio, sourceFiles,
} from "./statistics.js";

const number = (value) => value == null ? "未采集" : value.toLocaleString("zh-CN");
const parseNames = {
  parsed: "已解析", unsupported: "语言暂不支持", skipped: "受限跳过",
  failed: "解析失败", unavailable: "解析器不可用", changed: "变化待重扫",
};
const countNames = { counted: "已计数", unsupported: "未计数", unavailable: "计数工具不可用", changed: "变化待重扫", skipped: "已跳过", failed: "计数失败" };
const parsingStates = ["parsed", "unsupported", "skipped", "failed", "unavailable", "changed"];
const lineParts = [
  { key: "code", name: "代码", color: "#2563eb" },
  { key: "comments", name: "注释", color: "#13b8a6" },
  { key: "blanks", name: "空行", color: "#94a3b8" },
];
const languageColors = { typescript: "#3075f6", python: "#12a698", css: "#8b5cf6", javascript: "#d89b1d", html: "#e67b4c" };

function RelativeBar({ value, total, color }) {
  return <span className="stats-relative-bar" style={color ? { "--rank-color": color } : undefined} aria-hidden="true">
    <span style={{ width: `${(ratio(value, total) || 0) * 100}%` }} />
  </span>;
}

function ParsingBar({ parsing }) {
  return <div className="stats-parsing-bar" role="img" aria-label={parsingStates
    .filter((state) => parsing[state] > 0)
    .map((state) => `${parseNames[state]} ${number(parsing[state])} 文件`).join("；")}>
    {parsingStates.filter((state) => parsing[state] > 0).map((state) =>
      <span key={state} className={`state-${state}`} style={{ flex: parsing[state] }}
        title={`${parseNames[state]} ${number(parsing[state])} 文件`} />,
    )}
  </div>;
}

function MethodDetails({ data }) {
  const parserLimits = data.coverage?.parserLimits;
  return <details className="stats-method">
    <summary>统计口径与工具</summary>
    <p>按文件路径去重。代码、注释与空行由 scc 计数；文件语言按扫描器支持的扩展名识别。</p>
    <p>统计范围为本次盘点识别的源码文件。Git 忽略项、依赖安装目录、构建和运行数据目录排除；未知扩展名、二进制和未能读取的内容不补算代码行。</p>
    <p>行数与中位数仅基于已计数文件；部分计数会明确标注，未计数文件不当作零行。</p>
    <p>已计数文件代码行中位数：{number(fileMedian(sourceFiles(data)))} 行。</p>
    <p>{data.metrics?.tool?.version || "scc 未准备"}</p>
    {data.metrics?.tool?.message && <p>{data.metrics.tool.message}</p>}
    {data.coverage?.parsingTool && <p className="stats-runtime">
      {data.coverage.parsingTool.status === "ready"
        ? `Node ${data.coverage.parsingTool.version} · ${data.coverage.parsingTool.executable}`
        : data.coverage.parsingTool.message}
    </p>}
    {parserLimits && <p>解析预算：{number(parserLimits.files)} 文件、单文件 {number(parserLimits.fileBytes / 1024)} KiB、总计 {number(parserLimits.totalBytes / 1024 / 1024)} MiB。</p>}
    <p>“支持范围内完成率”以全部文件减去语言暂不支持的文件为分母。静态引用解析不代表测试覆盖或运行时行为。</p>
  </details>;
}

function ParsingSummary({ data, files, onOpen }) {
  const parsing = parserSummary(data);
  if (!parsing) return <p className="stats-empty">解析范围未采集</p>;
  const attention = files.filter(needsAttention);
  return <>
    <h3>解析范围</h3>
    <div className="stats-completion">
      <strong>{percent(parsing.parsed, parsing.supported)}</strong>
      <span>支持范围内完成率</span>
      <small>{number(parsing.parsed)} / {number(parsing.supported)} 文件</small>
    </div>
    <div className="stats-scope-ratio"><span>全部文件已解析比例</span><strong>{percent(parsing.parsed, parsing.total)}</strong></div>
    <div className="stats-status-list">
      {parsingStates.filter((state) => parsing[state] > 0 || state === "parsed").map((state) =>
        <button key={state} onClick={() => onOpen({ kind: "coverage", filter: state })}>
          <span><i className={`stats-dot state-${state}`} />{parseNames[state]}</span><strong>{number(parsing[state] || 0)}</strong>
        </button>,
      )}
    </div>
    {attention.length > 0 && <button className="stats-attention" onClick={() => onOpen({ kind: "coverage", filter: "attention" })}>
      <CircleAlert size={17} />
      <span><strong>{number(attention.length)} 个文件需要查看</strong><code title={attention[0].path}>{attention[0].path}</code></span>
      <ArrowRight size={16} />
    </button>}
    <button className="text-button stats-coverage-link" onClick={() => onOpen({ kind: "coverage" })}>查看解析详情 <ArrowRight size={14} /></button>
    <MethodDetails data={data} />
  </>;
}

function FileTable({ files, data, onSource, limit = 30 }) {
  const [visible, setVisible] = useState(limit);
  useEffect(() => setVisible(limit), [files, limit]);
  const previewIds = useMemo(() => new Set((data.files || []).map((file) => file.id)), [data.files]);
  if (!files.length) return <p className="stats-empty">没有符合条件的文件</p>;
  return <>
    <div className="stats-file-list">
      {files.slice(0, visible).map((file) => <div className="stats-file-row" key={file.id}>
        <button className="stats-file-path" title={file.path} disabled={!previewIds.has(file.id)} onClick={() => onSource({ path: file.id })}>
          <FileCode2 size={15} /><code>{file.path}</code><ArrowRight size={13} />
        </button>
        <span>{number(isCounted(file) ? file.metrics.code : null)} 代码行</span>
        <small>{countNames[file.countStatus] || file.countStatus} · {parseNames[file.parseStatus] || file.parseStatus}</small>
        {needsAttention(file) && <p>{file.captureReason || file.parseReason || file.countReason || "请查看文件状态"}</p>}
      </div>)}
    </div>
    {files.length > visible && <button className="text-button stats-load-more" onClick={() => setVisible((value) => value + limit)}>再显示 {limit} 个文件（剩余 {number(files.length - visible)}）</button>}
  </>;
}

export function MetricsDashboard({ data, onOpen, onSource }) {
  const files = useMemo(() => sourceFiles(data), [data]);
  const ready = data.metrics?.tool?.status === "ready";
  const total = useMemo(() => aggregateFiles(files, ready), [files, ready]);
  const [unit, setUnit] = useState("code");
  const [directory, setDirectory] = useState("");
  const [allDirectories, setAllDirectories] = useState(false);
  const [filesOpen, setFilesOpen] = useState(false);
  const [fileLanguage, setFileLanguage] = useState("");
  const [fileQuery, setFileQuery] = useState("");
  const fileSection = useRef(null);
  const languages = useMemo(() => ranked(languageRows(files, ready), unit), [files, ready, unit]);
  const directories = useMemo(() => ranked(directoryRows(files, directory, ready), unit), [files, directory, ready, unit]);
  const scopedFiles = useMemo(() => files.filter((file) => !directory || file.path.startsWith(`${directory}/`)), [files, directory]);
  const directoryTotal = aggregateFiles(scopedFiles, ready);
  const scopedLanguages = useMemo(() => ranked(languageRows(scopedFiles, ready), "files"), [scopedFiles, ready]);
  useEffect(() => {
    if (fileLanguage && !scopedLanguages.some((row) => row.name === fileLanguage)) setFileLanguage("");
  }, [fileLanguage, scopedLanguages]);
  function changeDirectory(path) {
    setDirectory(path);
    setFileLanguage("");
    setFileQuery("");
  }
  function openLanguage(name) {
    setDirectory("");
    setFileQuery("");
    setFileLanguage(name);
    setFilesOpen(true);
  }
  const filteredFiles = useMemo(() => files.filter((file) =>
    (!directory || file.path.startsWith(`${directory}/`)) &&
    (!fileLanguage || file.language === fileLanguage) &&
    file.path.toLowerCase().includes(fileQuery.toLowerCase()),
  ).sort((a, b) => (b.metrics?.code ?? -1) - (a.metrics?.code ?? -1) || a.path.localeCompare(b.path)), [files, directory, fileLanguage, fileQuery]);
  useEffect(() => { if (filesOpen) fileSection.current?.scrollIntoView({ block: "nearest" }); }, [filesOpen, fileLanguage]);
  const unitLabel = unit === "code" ? "代码行" : "文件";
  return <div className="stats-dashboard">
    <div className="stats-toolbar">
      <span className="stats-toolbar-scope">全部源码文件</span>
      <div className="stats-filter-group" role="group" aria-label="排名依据"><button aria-pressed={unit === "code"} onClick={() => setUnit("code")}>按代码行</button><button aria-pressed={unit === "files"} onClick={() => setUnit("files")}>按文件数</button></div>
    </div>
    {total.status !== "complete" && <p className="stats-notice" role="status">{total.code == null ? "代码行数尚未采集，文件数量仍可查看。" : `以下行数基于 ${number(total.countedFiles)} / ${number(total.files)} 个已计数文件；其余文件不按零行计算。`}</p>}
    <div className="stats-columns">
      <div className="stats-main">
        <section className="stats-section stats-composition">
          <div className="stats-section-heading"><h3>行构成</h3><span>{number(total.lines)} 总行数{total.status === "partial" ? "（部分）" : ""}</span></div>
          {total.lines > 0 ? <div className="stats-composition-bar" role="img" aria-label={lineParts.map((part) => `${part.name} ${number(total[part.key])} 行，占 ${percent(total[part.key], total.lines)}`).join("；")}>
            {lineParts.filter((part) => total[part.key] > 0).map((part) => <span key={part.key} style={{ width: `${ratio(total[part.key], total.lines) * 100}%`, background: part.color }} title={`${part.name} ${percent(total[part.key], total.lines)}`}>
              {ratio(total[part.key], total.lines) >= .08 && percent(total[part.key], total.lines)}
            </span>)}
          </div> : <p className="stats-empty">{total.lines === 0 ? "已计数文件没有内容" : "行构成未采集"}</p>}
          <div className="stats-composition-legend">{lineParts.map((part) => <div key={part.key}>
            <strong><i className="stats-dot" style={{ background: part.color }} />{part.name}</strong>
            <span>{number(total[part.key])} 行</span><small>{percent(total[part.key], total.lines)}</small>
          </div>)}</div>
        </section>
        <section className="stats-section">
          <div className="stats-section-heading"><h3>语言分布</h3><span>{number(total.files)} 文件 · 按{unitLabel}排序</span></div>
          <div className="stats-rank-head"><span>语言</span><span>{unitLabel}</span><span>占比</span></div>
          <div className="stats-rank-table">{languages.map((row) => <button className="stats-rank-row" key={row.name} onClick={() => openLanguage(row.name)} aria-label={`查看 ${languageName(row.name)} 文件`}>
            <span className="stats-language-name"><i className="stats-dot" style={{ background: languageColors[row.name] || "#64748b" }} />{languageName(row.name)}</span><RelativeBar value={row[unit]} total={total[unit]} color={languageColors[row.name]} /><strong>{number(row[unit])}</strong><span>{percent(row[unit], total[unit])}</span>
          </button>)}</div>
          {!languages.length && <p className="stats-empty">暂无语言统计</p>}
        </section>
        <section className="stats-section stats-directory-section">
          <div className="stats-section-heading"><h3>目录排名</h3><button className="text-button" onClick={() => setAllDirectories((value) => !value)}>{allDirectories ? "收起目录" : "查看全部目录"}<ArrowRight size={14} /></button></div>
          {directory && <nav className="stats-breadcrumb" aria-label="统计目录"><button onClick={() => changeDirectory("")}>全部目录</button>{directory.split("/").filter(Boolean).map((part, index, parts) => <React.Fragment key={index}><ChevronRight size={12} /><button onClick={() => changeDirectory(parts.slice(0, index + 1).join("/"))}>{part}</button></React.Fragment>)}</nav>}
          <div className="stats-rank-head"><span>目录 / 文件</span><span>{unitLabel}</span><span>占当前目录</span></div>
          <div className="stats-rank-table">{directories.slice(0, allDirectories ? undefined : 3).map((row, index) => <button className="stats-rank-row stats-directory-row" key={row.path} title={row.path}
            onClick={() => row.kind === "directory" ? changeDirectory(row.path) : onSource({ path: row.path })}
            disabled={row.kind === "file" && !(data.files || []).some((file) => file.id === row.path)}>
            <span><small className="stats-rank-index">{index + 1}</small>{row.kind === "directory" ? <Folder size={14} /> : <FileCode2 size={14} />}<code>{row.name}</code></span>
            <RelativeBar value={row[unit]} total={directoryTotal[unit]} /><strong>{number(row[unit])}</strong><span>{percent(row[unit], directoryTotal[unit])}<ChevronRight size={13} /></span>
          </button>)}</div>
          {!directories.length && <p className="stats-empty">当前目录没有文件</p>}
        </section>
      </div>
      <aside className="stats-aside"><ParsingSummary data={data} files={files} onOpen={onOpen} /></aside>
    </div>
    <section className="stats-file-section" ref={fileSection}>
      <button className="stats-file-disclosure" aria-expanded={filesOpen} onClick={() => setFilesOpen((value) => !value)}><ChevronRight size={15} /><strong>文件明细</strong><span>{number(filteredFiles.length)} 文件</span></button>
      {filesOpen && <>
        <div className="stats-file-tools"><label className="stats-search"><Search size={15} /><input aria-label="搜索统计文件" placeholder="搜索文件路径" value={fileQuery} onChange={(event) => setFileQuery(event.target.value)} /></label>
          <SelectMenu label="筛选文件语言" value={fileLanguage} onChange={setFileLanguage} options={[
            { value: "", label: "全部语言", detail: number(scopedFiles.length) },
            ...scopedLanguages.map((row) => ({ value: row.name, label: languageName(row.name), detail: number(row.files) })),
          ]} />
          {directory && <button className="stats-scope-chip" title={directory} onClick={() => changeDirectory("")}><code>{directory}</code><X size={12} /><span className="sr-only">清除目录范围</span></button>}
          {(fileQuery || fileLanguage) && <button className="text-button" onClick={() => { setFileQuery(""); setFileLanguage(""); }}>重置筛选</button>}
        </div><FileTable files={filteredFiles} data={data} onSource={onSource} />
      </>}
    </section>
  </div>;
}

export function CoverageDashboard({ data, view, onOpen, onSource, children }) {
  const files = useMemo(() => sourceFiles(data), [data]);
  const parsing = parserSummary(data);
  const [filter, setFilter] = useState(view.filter || "attention");
  const [query, setQuery] = useState("");
  const attention = useMemo(() => files.filter(needsAttention), [files]);
  const unsupported = files.filter((file) => file.parseStatus === "unsupported");
  const filtered = useMemo(() => files.filter((file) =>
    (filter === "all" || (filter === "attention" ? needsAttention(file) : file.parseStatus === filter)) &&
    file.path.toLowerCase().includes(query.toLowerCase()),
  ), [files, filter, query]);
  const languages = useMemo(() => ranked(languageRows(files), "files"), [files]);
  if (!parsing) return <p className="stats-empty">扫描范围尚未采集</p>;
  const counting = data.coverage.counting;
  return <div className="stats-dashboard stats-coverage-dashboard">
    <section className="stats-section stats-coverage-distribution">
      <div className="stats-section-heading"><h3>全部文件的解析分布</h3><span>全部 {number(parsing.total)} 文件 · 支持范围内完成率 <strong>{percent(parsing.parsed, parsing.supported)}</strong></span></div>
      <ParsingBar parsing={parsing} />
      <p className="stats-counting-inline">已计数 {number(counting.counted)} / {number(counting.total)} 文件 · 引用解析 {number(parsing.parsed)} / {number(parsing.supported)} 个支持的文件</p>
      <div className="stats-parsing-legend">{parsingStates.filter((state) => parsing[state] > 0 || state === "parsed").map((state) => <button key={state} onClick={() => setFilter(state)}><i className={`stats-dot state-${state}`} />{parseNames[state]} <strong>{number(parsing[state] || 0)}</strong><span>{percent(parsing[state] || 0, parsing.total)}</span></button>)}</div>
    </section>
    <div className="stats-columns">
      <div className="stats-main">
        <section className="stats-section">
          <div className="stats-section-heading"><h3>文件解析状态</h3><span>{number(filtered.length)} 文件</span></div>
          <div className="stats-file-tools stats-coverage-tools"><div className="stats-filter-group">
            {[["attention", `需要查看 ${number(attention.length)}`], ["unsupported", `语言暂不支持 ${number(unsupported.length)}`], ["all", "全部文件"]].map(([value, label]) => <button key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}>{label}</button>)}
            {!["attention", "unsupported", "all"].includes(filter) && <button aria-pressed="true" onClick={() => setFilter("attention")}>{parseNames[filter]}</button>}
          </div><label className="stats-search"><Search size={15} /><input aria-label="搜索解析文件" placeholder="搜索文件路径" value={query} onChange={(event) => setQuery(event.target.value)} /></label></div>
          {filter === "attention" && !attention.length ? <p className="stats-empty">当前没有需要查看的文件；语言暂不支持的文件单独列出。</p> : <FileTable files={filtered} data={data} onSource={onSource} />}
        </section>
        <section className="stats-section">
          <div className="stats-section-heading"><h3>按语言查看</h3><span>静态引用解析</span></div>
          <table className="stats-language-status"><thead><tr><th>语言</th><th>文件</th><th>已解析</th><th>暂不支持</th><th>其他状态</th></tr></thead><tbody>{languages.map((row) => {
            const members = files.filter((file) => file.language === row.name);
            const parsed = members.filter((file) => file.parseStatus === "parsed").length;
            const notSupported = members.filter((file) => file.parseStatus === "unsupported").length;
            const other = members.length - parsed - notSupported;
            return <tr key={row.name}><th>{languageName(row.name)}</th><td>{number(members.length)}</td><td>{number(parsed)}</td><td>{number(notSupported)}</td><td className={other ? "stats-warning" : ""}>{number(other)}</td></tr>;
          })}</tbody></table>
        </section>
        {children}
      </div>
      <aside className="stats-aside">
        <h3>语言支持范围</h3><p className="stats-footnote">Python、JavaScript、TypeScript 支持引用解析。其他语言仍参与代码计数。</p>
        <div className="stats-unsupported-languages">{ranked(languageRows(unsupported), "files").map((row) => <div key={row.name}><strong>{languageName(row.name)}</strong><span>{number(row.files)} 文件</span></div>)}</div>
        <p className="stats-footnote">“语言暂不支持”单独列出，不计入需要处理的解析异常。</p>
        <button className="text-button stats-coverage-link" onClick={() => onOpen({ kind: "metrics" })}>查看代码规模与构成 <ArrowRight size={14} /></button>
        <MethodDetails data={data} />
      </aside>
    </div>
  </div>;
}
