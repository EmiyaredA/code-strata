import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { transform } from 'esbuild';
import { conversationRecords, toolRecordTitle } from '../src/exploration-api.js';

test('chat presents one record per tool call, including legacy history and out-of-order results', () => {
  const message = (seq, run_id, kind, content) => ({ seq, run_id, kind, content });
  const records = conversationRecords([
    message(1, 'old', 'tool_call', { name: 'read_source', arguments: { path: 'main.py' } }),
    message(2, 'old', 'tool_result', { name: 'read_source', result: { endLine: 6 } }),
    message(3, 'new', 'tool_call', { name: 'query_code', callId: 'a' }),
    message(4, 'new', 'tool_call', { name: 'query_code', callId: 'b' }),
    message(5, 'new', 'tool_result', { name: 'query_code', callId: 'b', error: 'unavailable' }),
    message(6, 'new', 'tool_result', { name: 'query_code', callId: 'a', result: { nodes: 2 } }),
  ]);
  assert.equal(records.length, 3);
  assert.equal(records[0].result.result.endLine, 6);
  assert.equal(records[1].result.result.nodes, 2);
  assert.equal(records[2].result.error, 'unavailable');
  assert.deepEqual(toolRecordTitle(records[0].content), { label: '读取源码', scope: 'main.py' });
});

test('Pi extension registers only app tools, forwards the run capability and preserves errors', async () => {
  const source = await readFile(new URL('../../../scripts/exploration/pi-tools.ts', import.meta.url), 'utf8');
  const compiled = await transform(source, { loader: 'ts', format: 'esm' });
  const extension = await import('data:text/javascript;base64,' + Buffer.from(compiled.code).toString('base64'));
  const definition = { name: 'query_code', description: 'static source', inputSchema: { type: 'object', properties: { view: { type: 'string' } } }, annotations: { readOnlyHint: true } };
  const values = { CODE_STRATA_TOOL_DEFINITIONS: JSON.stringify([definition]), CODE_STRATA_TOOL_URL: 'http://127.0.0.1:1234', CODE_STRATA_TOOL_TOKEN: 'test-only-capability', CODE_STRATA_RUN_ID: 'test-run' };
  const previous = Object.fromEntries(Object.keys(values).map(k => [k, process.env[k]]));
  const originalFetch = globalThis.fetch;
  try {
    Object.assign(process.env, values);
    const registered = [];
    extension.default({ registerTool: tool => registered.push(tool) });
    assert.equal(registered.length, 1);
    assert.deepEqual(registered[0].parameters, definition.inputSchema);
    assert.deepEqual(registered[0].annotations, definition.annotations);
    const controller = new AbortController();
    let failed = false;
    globalThis.fetch = async (url, options) => {
      assert.equal(url, 'http://127.0.0.1:1234/api/explore/tools');
      assert.equal(options.headers['X-Code-Strata-Run'], 'test-only-capability');
      assert.deepEqual(JSON.parse(options.body), { runId: 'test-run', name: 'query_code', arguments: { view: 'functions' } });
      assert.equal(options.signal, controller.signal);
      return { ok: !failed, json: async () => failed ? { error: 'snapshot expired' } : { nodes: [], relations: [], snapshotId: 'frozen' } };
    };
    const success = await registered[0].execute('tool-call', { view: 'functions' }, controller.signal);
    assert.equal(success.isError, false);
    assert.equal(JSON.parse(success.content[0].text).snapshotId, 'frozen');
    failed = true;
    const failure = await registered[0].execute('tool-call', { view: 'functions' }, controller.signal);
    assert.equal(failure.isError, true);
    assert.equal(JSON.parse(failure.content[0].text).error, 'snapshot expired');
  } finally {
    globalThis.fetch = originalFetch;
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
  }
});
