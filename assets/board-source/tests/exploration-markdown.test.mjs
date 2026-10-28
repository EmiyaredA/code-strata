import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { markdownBlocks } from '../src/markdown-blocks.js';

test('a reply table keeps source locations, cell formatting and column alignment', () => {
  const blocks = markdownBlocks('主要入口：\r\n\r\n| 入口 | 源码位置 | 作用 |\r\n| :--- | :---: | ---: |\r\n| 桌面 | `desktop/src/main.ts:656` | 调用 **start** |\r\n| 服务 | [启动](source:backend/main.py:121) | 创建应用 |\r\n\r\n关键关系如下');
  const table = blocks.find(block => block.kind === 'table');
  assert.deepEqual(table.header, ['入口', '源码位置', '作用']);
  assert.deepEqual(table.align, ['left', 'center', 'right']);
  assert.deepEqual(table.rows, [['桌面', '`desktop/src/main.ts:656`', '调用 **start**'], ['服务', '[启动](source:backend/main.py:121)', '创建应用']]);
  assert.equal(blocks.at(-1).text, '关键关系如下');
});

test('tables accept optional outer pipes and preserve escaped or code-span pipes', () => {
  const [table] = markdownBlocks('名称 | 表达式\n--- | ---\nA\\|B | `left|right`\nC | ``a`|b``\n末尾缺列 |\n额外 | 保留 | 忽略');
  assert.equal(table.kind, 'table');
  assert.deepEqual(table.rows, [['A|B', '`left|right`'], ['C', '``a`|b``'], ['末尾缺列', ''], ['额外', '保留']]);
});

test('ordinary pipe text, incomplete streaming headers and code fences do not become tables', () => {
  for (const text of ['A | B\n---', 'A | B\n:-- | :', '普通文字\n---']) {
    assert.ok(markdownBlocks(text).every(block => block.kind !== 'table'));
  }
  const fenced = markdownBlocks('```md\n| A | B |\n|---|---|\n|1|2|\n```\n~~~text\n| C | D |\n|---|---|');
  assert.equal(fenced.length, 2);
  assert.ok(fenced.every(block => block.kind === 'code'));
  assert.match(fenced[1].text, /C \| D/);
  assert.deepEqual(markdownBlocks('| A |\n|---|')[0].rows, []);
});

const compiled = await build({ entryPoints: [new URL('../src/ExplorationMarkdown.jsx', import.meta.url).pathname], bundle: true, write: false, platform: 'node', format: 'esm', logLevel: 'silent' });
const { Markdown } = await import('data:text/javascript;base64,' + Buffer.from(compiled.outputFiles[0].text).toString('base64'));

test('table cells render semantic headers and source buttons while escaping untrusted HTML', () => {
  const html = renderToStaticMarkup(React.createElement(Markdown, { text: '| 入口 | 说明 |\n|---|---|\n| `src/main.ts:12` | **启动** `<img>` |\n| [源码](source:main.py:4) | <script>alert(1)</script> |\n| [非法](javascript:alert) | [文档](https://example.com) |', onSource() {} }));
  assert.match(html, /<table/);
  assert.equal((html.match(/scope="col"/g) || []).length, 2);
  assert.equal((html.match(/class="explore-source-link"/g) || []).length, 2);
  assert.match(html, /<strong>启动<\/strong>/);
  assert.match(html, /<code>&lt;img&gt;<\/code>/);
  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.doesNotMatch(html, /href="javascript:/);
  assert.match(html, /href="https:\/\/example.com"/);
});

test('existing headings, bullets and fenced code remain readable alongside tables', () => {
  const html = renderToStaticMarkup(React.createElement(Markdown, { text: '## 入口\n- **启动**\n```ts\nconst x = "<script>";\n```', onSource() {} }));
  assert.match(html, /<h4>入口<\/h4>/);
  assert.match(html, /explore-bullet/);
  assert.match(html, /<pre>const x = &quot;&lt;script&gt;&quot;;<\/pre>/);
});
