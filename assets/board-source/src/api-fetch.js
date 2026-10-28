const reloadReads = new Set(['/api/code/query', '/api/explore/read']);

function pause(ms, signal) {
  return new Promise((resolve, reject) => {
    const aborted = () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); };
    const timer = setTimeout(() => { signal?.removeEventListener('abort', aborted); resolve(); }, ms);
    signal?.addEventListener('abort', aborted, { once: true });
    if (signal?.aborted) aborted();
  });
}

// Reconnect reads during local development without reloading React state.
// An uncertain POST result must never replay a prompt or start another task.
export async function apiFetch(path, options = {}, runtime = {}) {
  const development = runtime.development ?? (typeof document !== 'undefined' && Boolean(document.querySelector('meta[name="code-strata-dev"]')));
  const fetcher = runtime.fetcher || fetch, wait = runtime.wait || pause, now = runtime.now || Date.now;
  const method = (options.method || 'GET').toUpperCase();
  const read = method === 'GET' || method === 'HEAD' || (method === 'POST' && reloadReads.has(path));
  // Large projects may need a fresh scan before the replacement starts serving.
  const deadline = now() + (read ? 120000 : 30000);
  for (;;) {
    options.signal?.throwIfAborted();
    let response;
    try {
      response = await fetcher(path, options);
    } catch (error) {
      if (!development || !read || error.name === 'AbortError' || now() >= deadline) throw error;
      await wait(300, options.signal);
      continue;
    }
    if (!development || ![502, 503, 504].includes(response.status) || now() >= deadline) return response;
    // The reload gate explicitly guarantees this POST was not dispatched.
    const rejectedBeforeDispatch = !read && response.status === 503 &&
      await response.clone().json().then(body => body.retryable === true).catch(() => false);
    if (!read && !rejectedBeforeDispatch) return response;
    await wait(300, options.signal);
  }
}
