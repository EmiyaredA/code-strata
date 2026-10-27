import assert from "node:assert/strict";
import { test } from "node:test";
import {
  aggregateFiles, directoryRows, fileMedian, languageRows, needsAttention,
  parserSummary, percent, ranked, sourceFiles,
} from "../assets/board-source/src/statistics.js";

const file = (path, code, extra = {}) => ({
  id: path, path, language: "typescript", category: "source",
  countStatus: "counted", parseStatus: "parsed",
  metrics: { code, comments: 1, blanks: 2, lines: code + 3 }, ...extra,
});

test("source inventory includes every origin category and deduplicates paths", () => {
  const a = file("vendor/a.ts", 10, { category: "third-party" });
  const b = file("tests/b.ts", 20, { category: "test" });
  const c = file("generated/c.ts", 30, { category: "generated" });
  const files = sourceFiles({ inventory: [a, b, c, a, file("package.json", 100, { category: "config" })] });
  assert.equal(files.length, 3);
  assert.equal(aggregateFiles(files).code, 60);
});

test("missing counts stay unknown and partial statistics never treat them as zero", () => {
  const missing = file("missing.ts", 0, { countStatus: "unavailable", metrics: null });
  const partial = aggregateFiles([file("a.ts", 10), missing]);
  assert.equal(partial.status, "partial");
  assert.equal(partial.code, 10);
  assert.equal(partial.countedFiles, 1);
  assert.equal(fileMedian([file("a.ts", 10), missing]), 10);
  assert.equal(aggregateFiles([missing]).code, null);
  assert.equal(aggregateFiles([], false).code, null);
  assert.equal(aggregateFiles([], true).code, 0);
  assert.equal(fileMedian([]), null);
  assert.equal(fileMedian([file("a", 0), file("b", 9)]), 4.5);
});

test("directory drilldown partitions each level without counting descendants twice", () => {
  const files = [file("web/src/a.ts", 10), file("web/tests/b.ts", 20), file("backend/main.py", 5), file("root.ts", 2)];
  const root = ranked(directoryRows(files));
  assert.equal(root.reduce((sum, row) => sum + row.code, 0), 37);
  assert.equal(root.find((row) => row.path === "web").code, 30);
  const web = directoryRows(files, "web");
  assert.deepEqual(web.map((row) => row.path), ["web/src", "web/tests"]);
  assert.equal(web.reduce((sum, row) => sum + row.code, 0), 30);
  assert.equal(directoryRows(files, "web/src")[0].kind, "file");
  assert.equal(directoryRows(files, "we").length, 0);
});

test("ranking units and percentages use their own denominator", () => {
  const files = [file("a", 100), file("b", 10, { language: "python" }), file("c", 5, { language: "python" })];
  assert.equal(ranked(languageRows(files), "code")[0].name, "typescript");
  assert.equal(ranked(languageRows(files), "files")[0].name, "python");
  assert.equal(percent(554796, 803646), "69.03%");
  assert.equal(percent(0, 0), "—");
  assert.equal(percent(null, 100), "—");
});

test("parsing scope keeps unsupported languages separate from actionable incomplete files", () => {
  const summary = parserSummary({ coverage: { parsing: { total: 3980, parsed: 3595, unsupported: 384, skipped: 1 } } });
  assert.equal(summary.supported, 3596);
  assert.equal(percent(summary.parsed, summary.total), "90.33%");
  assert.equal(percent(summary.parsed, summary.supported), "99.97%");
  assert.equal(needsAttention(file("a.css", 0, { parseStatus: "unsupported" })), false);
  assert.equal(needsAttention(file("a.ts", 0, { parseStatus: "skipped" })), true);
  assert.equal(needsAttention(file("a.css", 0, { parseStatus: "unsupported", countStatus: "unavailable" })), true);
  assert.equal(parserSummary({}), null);
});
