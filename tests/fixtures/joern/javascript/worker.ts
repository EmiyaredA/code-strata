import { allowed as permit, createKey, Store } from './barrel';

export async function uploadAsset(file: { name: string }, user: { enabled: boolean }) {
  const allowed = permit(user); // CASE alias-reexport
  if (!allowed) throw new Error('Forbidden');
  const { name } = file;
  let key = createKey(name); // CASE direct-call
  const store = new Store(); // CASE constructor
  function nested() {
    const key = 'inner'; // CASE shadow-inner
    return key;
  }
  const captured = () => key; // CASE closure-capture
  if (name.length > 5) key = key + '-long'; // CASE reassignment
  const url = store.put(key, file); // CASE method-call
  await Promise.resolve(url); // CASE async
  nested(); // CASE nested-call
  const 中文 = '😀'; const unicodeKey = createKey( // CASE unicode-multiline
    中文
  );
  return { key, url, unicodeKey, captured: captured() }; // CASE shorthand-reference
}

export function recurse(n: number): number {
  if (n <= 0) return 0;
  return recurse(n - 1); // CASE recursion
}

export function dispatch(handler: () => void) {
  handler(); // CASE unresolved-callback
}

export function dynamicCall(obj: Record<string, () => void>, name: string) {
  obj[name](); // CASE dynamic-target
}

export function cleanup() { return 'done'; }
export function control(items: number[]) {
  let total = 0;
  try {
    for (const item of items) { // CASE loop
      if (item < 0) continue;
      if (item > 10) break;
      total += item;
    }
    if (total) return total; // CASE early-return
    throw new Error('empty');
  } catch (error) {
    return -1;
  } finally {
    cleanup(); // CASE finally
  }
}

export function* generate() {
  yield createKey('one'); // CASE generator
}

export function overwritten() {
  let value = 1; // CASE flow-first-write
  value = 2; // CASE flow-last-write
  return value; // CASE flow-read
}
