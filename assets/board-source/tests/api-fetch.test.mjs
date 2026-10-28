import { test } from 'node:test';
import assert from 'node:assert/strict';
import { apiFetch } from '../src/api-fetch.js';

test('development read reconnects with the original token and signal; normal requests do not retry', async () => {
  const options = { headers: { 'X-Architecture-Token': 'unchanged' }, signal: new AbortController().signal };
  let calls = 0;
  const fetcher = async (_path, received) => {
    assert.equal(received, options);
    if (++calls === 1) throw new TypeError('Failed to fetch');
    return new Response('{}');
  };
  const response = await apiFetch('/api/project', options, { development: true, fetcher, wait: async () => {} });
  assert.equal(response.status, 200);
  assert.equal(calls, 2);
  calls = 0;
  await assert.rejects(apiFetch('/api/project', options, { development: false, fetcher }), /Failed to fetch/);
  assert.equal(calls, 1);
});

test('an uncertain POST never repeats an Agent prompt; only an explicit reload rejection can retry it', async () => {
  let calls = 0;
  const path = '/api/explore/conversations/id/messages';
  await assert.rejects(apiFetch(path, { method: 'POST', body: '{"text":"question"}' }, {
    development: true, fetcher: async () => { calls++; throw new TypeError('connection lost'); },
  }), /connection lost/);
  assert.equal(calls, 1);
  calls = 0;
  const response = await apiFetch(path, { method: 'POST' }, {
    development: true, wait: async () => {}, fetcher: async () => ++calls === 1
      ? new Response('{"retryable":true}', { status: 503 }) : new Response('{}', { status: 202 }),
  });
  assert.equal(response.status, 202);
  assert.equal(calls, 2);
});

test('abort stops reconnection and outage retries have a deadline', async () => {
  const controller = new AbortController();
  let calls = 0;
  await assert.rejects(apiFetch('/api/project', { signal: controller.signal }, {
    development: true, fetcher: async () => { calls++; throw new TypeError('offline'); },
    wait: async () => { controller.abort(); },
  }), error => error.name === 'AbortError');
  assert.equal(calls, 1);
  let clock = -20000;
  await assert.rejects(apiFetch('/api/project', {}, {
    development: true, now: () => clock += 20000, wait: async () => {},
    fetcher: async () => { throw new TypeError('offline'); },
  }), /offline/);
});
