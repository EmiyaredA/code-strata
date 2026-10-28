import test from "node:test";
import assert from "node:assert/strict";
import { readingContext, readingQuestion, readingPrompt, readingMessage, locateInMap, currentCodeNotice } from "../src/reading-navigation.js";

const data = { project: { root: "/project", name: "Example" }, snapshot: { id: "current" }, groups: [{ id: "upload", title: "上传", files: ["main.py", "store.py"] }], inventory: [{ path: "main.py" }, { path: "store.py" }], files: [] };
const fn = { id: "function:new", kind: "function", name: "complete", path: "main.py", range: { start: [90, 0], end: [95, 0] } };
const old = { ...fn, id: "function:old", snapshotId: "old", range: { start: [4, 0], end: [8, 0] } };

test("handoff keeps the full module scope, file path, function location and source snapshot", () => {
  const group = readingContext(data, { kind: "group", id: "upload" });
  assert.deepEqual(group.files, ["main.py", "store.py"]);
  assert.equal(group.snapshotId, "current");
  assert.equal(group.project, "/project");
  assert.match(readingQuestion(group), /模块「上传」/);
  assert.equal(readingContext(data, { kind: "file", id: "main.py" }).path, "main.py");
  const context = readingContext(data, fn);
  assert.deepEqual(context.range, fn.range);
  assert.match(readingQuestion(context), /函数「complete」/);
  const prompt = readingPrompt("解释校验", context);
  assert.match(prompt, /解释校验/);
  assert.match(prompt, /不沿用旧节点 ID 或行号/);
  assert.match(prompt, /main.py/);
  assert.doesNotMatch(prompt, /function:new/);
  assert.equal(readingPrompt("继续", null), "继续");
  assert.equal(readingMessage(prompt).text, "解释校验");
  assert.equal(readingMessage(prompt).context.path, "main.py");
  assert.deepEqual(readingMessage("旧主题的普通消息"), { text: "旧主题的普通消息" });
});

test("relations, variables, placeholders and unavailable projects cannot start a scoped reading", () => {
  for (const kind of ["edge", "relation", "statement", "summary", "entry", "variable"]) assert.equal(readingContext(data, { kind }), null);
  assert.equal(readingContext(data, { kind: "group", id: "missing" }), null);
  assert.equal(readingContext({ ...data, project: {} }, fn), null);
});

test("large module prompts include a bounded sample and the complete scope identifier", () => {
  const context = { ...readingContext(data, { kind: "group", id: "upload" }), files: Array.from({ length: 3000 }, (_, i) => `src/part${i}.ts`) };
  const prompt = readingPrompt("画图", context);
  assert.ok(prompt.length < 12000);
  const scope = JSON.parse(prompt.slice(prompt.indexOf("{\n")));
  assert.equal(scope.fileCount, 3000);
  assert.equal(scope.files.length, 30);
  assert.equal(scope.groupId, "upload");
});

test("same-snapshot node identity wins over duplicate names", async () => {
  const result = await locateInMap(data, { ...fn, snapshotId: "current" }, async () => ({ nodes: [{ ...fn, id: "other" }, fn] }));
  assert.equal(result.entry.focusId, fn.id);
  assert.equal(result.entry.fileEntry.focusId, "main.py");
  assert.equal(result.notice, "");
});

test("a moved function locates its current identity and does not reuse its old line or mutate the saved target", async () => {
  const before = structuredClone(old);
  const result = await locateInMap(data, old, async () => ({ nodes: [fn] }));
  assert.equal(result.entry.focusId, fn.id);
  assert.equal(result.notice, currentCodeNotice);
  assert.deepEqual(old, before);
  assert.equal(result.entry.range, undefined);
});

test("duplicate names on later pages prevent guessing even if an old ID is reused", async () => {
  const calls = [];
  const result = await locateInMap(data, old, async (snapshot, request) => {
    calls.push(request.offset);
    assert.equal(snapshot, "current");
    return request.offset === 0 ? { nodes: [{ ...fn, id: old.id }], nextOffset: 100 } : { nodes: [{ ...fn, id: "another" }] };
  });
  assert.deepEqual(calls, [0, 100]);
  assert.equal(result.entry.view, "files");
  assert.match(result.notice, /无法唯一确定/);
});

test("renamed functions fall back to the file; source links have no invented function identity", async () => {
  const result = await locateInMap(data, old, async () => ({ nodes: [{ ...fn, name: "different" }] }));
  assert.equal(result.entry.view, "files");
  const file = await locateInMap(data, { path: "main.py", snapshotId: "old" }, () => { throw new Error("must not query"); });
  assert.equal(file.entry.focusId, "main.py");
  assert.equal(file.notice, currentCodeNotice);
});

test("deleted files stay in the reading theme, without querying another file", async () => {
  const result = await locateInMap(data, { ...old, path: "deleted.py" }, () => { throw new Error("must not query"); });
  assert.match(result.error, /找不到该文件/);
  assert.equal(result.entry, undefined);
});

test("analysis failures, aborts and broken pagination surface instead of navigating to a guessed function", async () => {
  await assert.rejects(locateInMap(data, old, async () => ({ status: "failed", nodes: [] })), /分析失败/);
  const signal = new AbortController().signal;
  await assert.rejects(locateInMap(data, old, async (_, __, received) => {
    assert.equal(received, signal);
    throw new DOMException("Cancelled", "AbortError");
  }, signal), { name: "AbortError" });
  await assert.rejects(locateInMap(data, old, async () => ({ nodes: [], nextOffset: 0 })), /分页未前进/);
});
