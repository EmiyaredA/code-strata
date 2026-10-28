import { codeQuery, functionKinds } from "./code-model.js";

export function readingContext(data, target) {
  if (!data.project.root || !target) return null;
  const base = { project: data.project.root, projectName: data.project.name, snapshotId: data.snapshot.id };
  if (target.kind === "group") {
    const group = data.groups.find(g => g.id === target.id);
    return group ? { ...base, kind: "group", name: group.title, groupId: group.id, files: [...group.files] } : null;
  }
  if (target.kind !== "file" && !functionKinds.has(target.kind)) return null;
  const path = target.path || target.id;
  return { ...base, kind: target.kind, path, name: target.name || path.split("/").at(-1), range: target.range };
}

export function readingQuestion(context) {
  return `请解读${context.kind === "group" ? "模块" : context.kind === "file" ? "文件" : "函数"}「${context.name}」的职责和实现，整理关键阅读顺序，并生成有源码依据的阅读图。`;
}

export const readingScopeMarker = "\n\n已选代码范围（定位线索，请在本轮源码快照中重新查询，不沿用旧节点 ID 或行号；模块文件列表最多展示前 30 项）：\n";

export function readingPrompt(text, context) {
  if (!context) return text;
  const { serial, ...scope } = context;
  if (scope.files) { scope.fileCount = scope.files.length; scope.files = scope.files.slice(0, 30); }
  return `${text}${readingScopeMarker}${JSON.stringify(scope, null, 2)}`;
}

export function readingMessage(text) {
  const at = text.lastIndexOf(readingScopeMarker);
  if (at < 0) return { text };
  try {
    const context = JSON.parse(text.slice(at + readingScopeMarker.length));
    if (!["group", "file", ...functionKinds].includes(context.kind) || typeof context.name !== "string" || typeof context.snapshotId !== "string") return { text };
    return { text: text.slice(0, at), context };
  } catch { return { text }; }
}

export const currentCodeNotice = "已定位到当前扫描代码，历史源码仍可在原主题查看";

// A line number is never an identity across snapshots. Ambiguous names fall back
// to the file, even when an old line happens to contain another function now.
export async function locateInMap(data, target, query = codeQuery, signal) {
  const files = data.inventory || data.files;
  if (!files.some(f => (f.path || f.id) === target.path)) return { error: "当前扫描中找不到该文件，请重新扫描项目；历史源码仍可在原主题查看。" };
  const changed = target.snapshotId !== data.snapshot.id;
  const fileEntry = { view: "files", focusId: target.path, path: target.path, title: target.path.split("/").at(-1) };
  const notice = changed ? currentCodeNotice : "";
  if (!functionKinds.has(target.kind)) return { entry: fileEntry, notice };
  const symbols = [];
  let offset = 0;
  for (;;) {
    const page = await query(data.snapshot.id, { view: "symbols", focusId: target.path, offset, limit: 100 }, signal);
    if (page.status === "failed") throw new Error("当前文件分析失败，暂时无法定位。");
    symbols.push(...page.nodes || []);
    if (page.nextOffset == null) break;
    if (page.nextOffset <= offset) throw new Error("代码查询分页未前进，请重新扫描后重试。");
    offset = page.nextOffset;
  }
  const exact = !changed && symbols.find(n => n.id === target.id && n.path === target.path && n.kind === target.kind);
  const matches = symbols.filter(n => n.path === target.path && n.name === target.name && n.kind === target.kind);
  const found = exact || (matches.length === 1 ? matches[0] : null);
  if (!found) return { entry: fileEntry, notice: [notice, "无法唯一确定原函数，已打开对应文件。"].filter(Boolean).join("；") };
  return { entry: { ...fileEntry, view: "functions", focusId: found.id, title: found.name, fileEntry }, notice };
}
