import { apiFetch } from './api-fetch.js';

export const agentNames = { codex: "Codex", opencode: "OpenCode", dsh: "DeepSeek Harness", claude: "Claude Code", pi: "Pi" };

export async function explorationApi(path, body, signal) {
  const response = await apiFetch(path, {
    method: body === undefined ? "GET" : "POST", signal,
    headers: { "X-Architecture-Token": document.querySelector('meta[name="architecture-token"]')?.content || "",
      ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "读取会话失败");
  return result;
}

export async function loadConversation(id, signal) {
  const path = `/api/explore/conversations/${id}`;
  const result = await explorationApi(path, undefined, signal);
  let cursor = result.history.nextCursor;
  while (cursor !== null) {
    const page = await explorationApi(`${path}?cursor=${cursor}`, undefined, signal);
    result.history.messages.push(...page.history.messages);
    cursor = page.history.nextCursor;
  }
  return result;
}

export function freshnessLabel(status) {
  return { current: "与当前代码一致", stale: "已过时", checking: "正在检查代码变化", unchecked: "待检查", error: "无法检查代码变化" }[status] || "待检查";
}

// Tool calls/results remain separate durable events; present them as one record.
export function conversationRecords(messages) {
  const records = [], pending = new Map();
  const key = message => message.content.callId || `${message.run_id}:${message.content.name}`;
  for (const message of messages) {
    if (message.kind === 'tool_call') {
      const record = { ...message, result: null };
      records.push(record);
      const id = key(message);
      if (!pending.has(id)) pending.set(id, []);
      pending.get(id).push(record);
    } else if (message.kind === 'tool_result') {
      const call = pending.get(key(message))?.shift();
      if (call) call.result = message.content;
      else records.push(message);
    } else records.push(message);
  }
  return records;
}

export function toolRecordTitle(content) {
  const labels = { search_code: '搜索代码', query_code: '查询代码关系', read_source: '读取源码', save_view: '整理旧阅读图', save_diagrams: '生成 UML', list_diagrams: '读取项目图集', get_diagram: '读取 UML 版本' };
  const args = content.arguments || {};
  const scope = content.name === 'search_code' ? args.text : content.name === 'read_source' ? args.path : content.name === 'save_diagrams' ? args.diagrams?.map(d=>d.title).join('、') : content.name === 'save_view' ? args.title :
    { functions: '函数调用', files: '文件依赖', logic: '函数结构', symbols: '源码符号', references: '符号引用' }[args.view];
  return { label: labels[content.name] || '分析代码', scope: scope || '' };
}
