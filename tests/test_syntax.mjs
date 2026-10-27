import assert from "node:assert/strict";
import { test } from "node:test";
import { highlightedLines, sliceTokens, syntaxLanguage } from "../assets/board-source/src/syntax.js";

const restore = (lines) => lines.map((line) => line.map((token) => token.text).join("")).join("\n");
test("multiline comments retain syntax state and original line boundaries", () => {
  const source = '/* first\nsecond */\nconst message = "hello";\n';
  const lines = highlightedLines(source, "javascript");
  assert.equal(restore(lines), source);
  assert.ok(lines[1].some((token) => token.className.includes("hljs-comment")));
  assert.ok(lines[2].some((token) => token.className.includes("hljs-keyword")));
  assert.ok(lines[2].some((token) => token.className.includes("hljs-string")));
});
test("HTML and entity-like source remain literal React text", () => {
  const source = '<script>alert("<img onerror=x>")</script> &lt; &amp; "中文"';
  assert.equal(restore(highlightedLines(source, "html")), source);
});
test("language inference covers evidence paths and unknown files stay plain", () => {
  assert.equal(syntaxLanguage("依据", "package.json"), "json");
  assert.equal(syntaxLanguage("tsx", "page.tsx"), "typescript");
  assert.equal(syntaxLanguage("", "style.css"), "css");
  assert.equal(syntaxLanguage("unknown", "README.unfamiliar"), null);
  assert.equal(restore(highlightedLines("a\n\n<foo>\n", "unknown")), "a\n\n<foo>\n");
});
test("syntax slices preserve UTF-16 ranges used by interactive symbol buttons", () => {
  const source = 'const 中文 = "🌿";';
  const line = highlightedLines(source, "typescript")[0];
  const start = source.indexOf('"');
  assert.equal(sliceTokens(line, start, source.length - 1).map((token) => token.text).join(""), '"🌿"');
  assert.equal(sliceTokens(line, 6, 8).map((token) => token.text).join(""), "中文");
  assert.ok(line.every((token) => source.slice(token.start, token.end) === token.text));
});
test("a long source snapshot keeps every line and its final newline", () => {
  const source = Array.from({ length: 3000 }, (_, index) => `const item${index} = ${index};`).join("\n") + "\n";
  const lines = highlightedLines(source, "javascript");
  assert.equal(lines.length, 3001);
  assert.equal(restore(lines), source);
});
