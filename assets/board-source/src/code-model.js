import { apiFetch } from './api-fetch.js';

const functionKinds = /* @__PURE__ */ new Set(["function", "method", "constructor", "lambda"]);
const kindNames = { file: "文件", class: "类", function: "函数", method: "方法", constructor: "构造函数", lambda: "匿名函数", variable: "变量", parameter: "参数", statement: "语句", call: "调用点", reference: "引用" };
function containsRange(outer, inner) {
  if (!outer || !inner) return false;
  const compare = (a, b) => a[0] - b[0] || a[1] - b[1];
  return compare(outer.start, inner.start) <= 0 && compare(outer.end, inner.end) >= 0;
}
function innermost(nodes, range) {
  return nodes.filter((n) => containsRange(n.range, range)).sort((a, b) => a.range.end[0] - a.range.start[0] - (b.range.end[0] - b.range.start[0]) || a.range.end[1] - a.range.start[1] - (b.range.end[1] - b.range.start[1]))[0];
}
function frameKey(frame) {
  return `${frame.view}:${frame.groupId || ""}:${frame.focusId || ""}${frame.moduleTopLevel ? ':module' : ''}`;
}
async function codeQuery(snapshotId, body, signal) {
  for (; ; ) {
    const response = await apiFetch("/api/code/query", { method: "POST", headers: { "Content-Type": "application/json", "X-Architecture-Token": document.querySelector('meta[name="architecture-token"]')?.content || "" }, body: JSON.stringify({ snapshotId, ...body }), signal });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "代码分析读取失败");
    if (data.status !== "building") return data;
    await new Promise((resolve, reject) => {
      const onAbort = () => {
        clearTimeout(timer);
        reject(new DOMException("Aborted", "AbortError"));
      };
      const timer = setTimeout(() => {
        signal?.removeEventListener("abort", onAbort);
        resolve();
      }, data.retryAfterMs || 350);
      signal?.addEventListener("abort", onAbort, { once: true });
      if (signal?.aborted) onAbort();
    });
  }
}
export {
  codeQuery,
  containsRange,
  frameKey,
  functionKinds,
  innermost,
  kindNames
};
