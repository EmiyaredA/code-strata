import React, { useState } from "react";
import { MetricsDashboard, CoverageDashboard } from "./StatisticsPanels.jsx";
import { percent } from "./statistics.js";
import { SyntaxCode } from "./SyntaxCode.jsx";
import {
  Layers,
  FileCode2,
  ChevronRight,
  ArrowLeft,
  ChevronDown,
  ArrowUpRight,
} from "lucide-react";

export const number = (value) =>
  value == null ? "未采集" : value.toLocaleString("zh-CN");
const categoryLabels = {
  language: "语言",
  framework: "框架",
  runtime: "运行时",
  build: "构建工具",
  storage: "存储",
  test: "测试工具",
};
const parsingStates = [
  ["unavailable", "解析器不可用", true],
  ["failed", "解析失败", true],
  ["changed", "变化待重扫", true],
  ["skipped", "受限跳过", false],
  ["unsupported", "不支持引用分析", false],
];
export function inventoryFiles(data) {
  return (data.inventory || data.files).filter((x) => x.category !== "config");
}
function StackTags({
  technologies,
  onOpen,
  active,
  limit,
  expandable = false,
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="stack-tags">
      {technologies.slice(0, expanded ? undefined : limit).map((tech) => (
        <button
          key={tech.id}
          className={`stack-tag category-${tech.category}`}
          aria-pressed={active === tech.id}
          aria-label={`技术栈 ${tech.name}`}
          title={`${categoryLabels[tech.category]} · 点击查看依据`}
          onClick={() => onOpen({ kind: "technology", id: tech.id })}
        >
          {tech.name}
        </button>
      ))}
      {technologies.length > limit && (
        <button
          className="stack-more"
          aria-expanded={expandable ? expanded : undefined}
          aria-label={
            expanded
              ? "收起技术标签"
              : `展开全部 ${technologies.length} 个技术标签`
          }
          onClick={() =>
            expandable
              ? setExpanded(!expanded)
              : onOpen({ kind: "technologies" })
          }
        >
          {expanded ? "收起" : `+${technologies.length - limit}`}
        </button>
      )}
    </div>
  );
}
function overviewTechnologies(data) {
  const all = [...(data.technologies || [])];
  const score = (t) =>
    t.category === "language"
      ? data.metrics?.languages[t.name.toLowerCase()]?.code ||
        t.languageEvidence.length
      : new Set(t.references.map((r) => r.path)).size;
  all.sort((a, b) => score(b) - score(a) || a.name.localeCompare(b.name));
  const quotas = {
    language: 2,
    framework: 2,
    build: 1,
    storage: 1,
    runtime: 1,
    test: 1,
  };
  const visible = [];
  for (const [category, limit] of Object.entries(quotas))
    visible.push(...all.filter((t) => t.category === category).slice(0, limit));
  for (const t of all)
    if (visible.length < 8 && !visible.includes(t)) visible.push(t);
  return [...visible, ...all.filter((t) => !visible.includes(t))];
}
export function ProjectOverview({ data, inspector, onOpen }) {
  const [collapsed, setCollapsed] = useState(false);
  const total = data.metrics?.total,
    parsing = data.coverage?.parsing;
  const technologies = overviewTechnologies(data);
  if (collapsed)
    return (
      <button
        className="overview-collapsed"
        onClick={() => setCollapsed(false)}
      >
        <ChevronRight size={14} />
        项目数据
      </button>
    );
  return (
    <section className="project-overview" aria-label="项目工程数据">
      <div className="overview-stack">
        <Layers size={20} />
        <div>
          <strong>技术栈</strong>
          {technologies.length ? (
            <StackTags
              technologies={technologies}
              onOpen={onOpen}
              active={inspector?.id}
              limit={8}
              expandable
            />
          ) : (
            <span className="overview-note">暂无识别结果</span>
          )}
        </div>
      </div>
      <button
        className="overview-metric overview-statistics"
        onClick={() => onOpen({ kind: "metrics" })}
        aria-label="查看工程统计"
        aria-haspopup="dialog"
      >
        <FileCode2 size={20} />
        <span className="overview-statistics-content">
          <strong>工程统计</strong>
          <span className="overview-statistics-grid">
            <span className="overview-scale">
              <span className="overview-big-number"><b>{total?.code == null ? "未采集" : number(total.code)}</b><small>{total?.code != null ? `行代码${total.status === "partial" ? "（部分）" : ""}` : "代码行"}</small></span>
              <small>{number(total?.files)} 文件</small>
            </span>
            <span className="overview-parsing">
              <span className="overview-big-number"><small>引用解析</small><b>{parsing ? percent(parsing.parsed, parsing.total) : "未采集"}</b></span>
              {parsing && <span className="overview-mini-bar" role="img" aria-label={`已解析 ${number(parsing.parsed)} / ${number(parsing.total)} 文件；比例 ${percent(parsing.parsed, parsing.total)}`}>
                {[["parsed", "已解析"], ...parsingStates.map(([state, label]) => [state, label])].filter(([state]) => parsing[state] > 0).map(([state, label]) => <span key={state} className={`state-${state}`} style={{ flex: parsing[state] }} title={`${label} ${number(parsing[state])} 文件`} />)}
              </span>}
            </span>
          </span>
        </span>
        <ChevronRight size={14} />
      </button>
      <button
        className="overview-collapse icon-button"
        aria-label="折叠项目数据"
        title="折叠项目数据"
        onClick={() => setCollapsed(true)}
      >
        <ChevronDown size={14} />
      </button>
    </section>
  );
}

function Evidence({ records, onSource }) {
  if (!records.length)
    return <p className="inspection-empty">未发现相关依据</p>;
  return (
    <div className="technology-evidence">
      {records.map((ref, i) => (
        <article key={i}>
          {ref.value && <strong>{ref.value}</strong>}
          {ref.scope && <small>范围：{ref.scope}</small>}
          {ref.note && <small>{ref.note}</small>}
          <button
            className="evidence-path"
            onClick={() => onSource(ref)}
            title={ref.path}
          >
            <code>
              {ref.path}
              {ref.line ? `:${ref.line}` : ""}
            </code>
            <ArrowUpRight size={13} />
          </button>
          {ref.selector && (
            <code className="evidence-selector">{ref.selector}</code>
          )}
          <SyntaxCode className="evidence-snippet" text={ref.text || ""} path={ref.path} />
        </article>
      ))}
    </div>
  );
}

function TechnologyDetails({ tech, onSource }) {
  return (
    <>
      <div className="technology-title">
        <span className={`stack-tag category-${tech.category}`}>
          {tech.name}
        </span>
        <span>{categoryLabels[tech.category]}</span>
      </div>
      {tech.languageEvidence.length > 0 && (
        <details>
          <summary>
            语言识别 · {number(tech.languageEvidence.length)} 文件
          </summary>
          <Evidence records={tech.languageEvidence} onSource={onSource} />
        </details>
      )}
      <details open>
        <summary>清单声明 · {number(tech.declarations.length)} 处</summary>
        <Evidence records={tech.declarations} onSource={onSource} />
      </details>
      <details open>
        <summary>锁定版本 · {number(tech.locked.length)} 条</summary>
        <Evidence records={tech.locked} onSource={onSource} />
      </details>
      <details>
        <summary>
          源码引用 · {number(new Set(tech.references.map((r) => r.path)).size)}{" "}
          文件 / {number(tech.references.length)} 处
        </summary>
        <Evidence records={tech.references} onSource={onSource} />
      </details>
      <p className="inspection-footnote">
        以上为静态证据，未观察实际安装版本或运行状态。
      </p>
    </>
  );
}
function CoverageDiagnostics({ diagnostics }) {
  const [open, setOpen] = useState(false),
    [limit, setLimit] = useState(50);
  const records = diagnostics.filter(
    (item) => !["coverage", "read"].includes(item.kind),
  );
  if (!records.length) return null;
  return (
    <details onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>引用与配置说明 · {number(records.length)} 项</summary>
      {open && (
        <>
          <p className="inspection-footnote">
            文件完成语法解析后，资源导入、动态引用或受限目标仍可能无法建立连线。这些说明不等于文件解析失败。
          </p>
          {records.slice(0, limit).map((item, index) => (
            <article className="file-stat" key={index}>
              <code>
                {item.path}
                {item.line ? `:${item.line}` : ""}
              </code>
              <span>{item.message}</span>
            </article>
          ))}
          {records.length > limit && (
            <button
              className="text-button"
              onClick={() => setLimit((count) => count + 50)}
            >
              再显示 50 项说明（剩余 {number(records.length - limit)}）
            </button>
          )}
        </>
      )}
    </details>
  );
}
export function InspectionPanel({
  data,
  view,
  onBack,
  onOpen,
  onSource,
  showHeader = true,
}) {
  const title = {
    technology: "技术栈依据",
    technologies: "项目技术栈",
    metrics: "代码规模与构成",
    coverage: "扫描范围",
  }[view.kind];
  const tech = data.technologies?.find((x) => x.id === view.id);
  return (
    <div className="inspection-panel">
      {showHeader && (
        <div className="inspection-header">
          <button className="text-button" onClick={onBack}>
            <ArrowLeft size={15} />
            返回代码结构
          </button>
          <h2>{title}</h2>
        </div>
      )}
      <div className="inspection-scroll" key={`${view.kind}:${view.id || ""}`}>
        {view.kind === "technology" && tech && (
          <TechnologyDetails tech={tech} onSource={onSource} />
        )}
        {view.kind === "technologies" && (
          <StackTags
            technologies={data.technologies || []}
            onOpen={onOpen}
            limit={Infinity}
          />
        )}
        {view.kind === "metrics" && (
          <MetricsDashboard data={data} onOpen={onOpen} onSource={onSource} />
        )}
        {view.kind === "coverage" && (
          <CoverageDashboard data={data} view={view} onOpen={onOpen} onSource={onSource}>
            <CoverageDiagnostics diagnostics={data.diagnostics || []} />
          </CoverageDashboard>
        )}
      </div>
    </div>
  );
}
export function ModuleStatistics({ group }) {
  if (!group?.stats) return null;
  const stats = group.stats;
  return (
    <section className="module-statistics" aria-label="所选模块统计">
      <div className="module-stat-summary">
        <span title="所选模块关联的源码文件"><b>{number(stats.total.files)}</b> 文件</span>
        <span title={`所选模块代码行数${stats.total.status === "partial" ? "（部分计数）" : ""}`}>
          <b>{number(stats.total.code)}</b>{stats.total.code != null ? " 行" : ""}{stats.total.status === "partial" ? "（部分）" : ""}
        </span>
        <span title="入向 / 出向静态引用处数">引用 <b>{number(stats.incoming)}</b> 入 / <b>{number(stats.outgoing)}</b> 出</span>
      </div>
    </section>
  );
}
