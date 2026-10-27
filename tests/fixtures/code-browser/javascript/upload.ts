import { allowed as canUpload, Store } from './barrel.js';
export async function uploadAsset(name: string, handler: (key: string) => void) {
  const 中文 = "😀"; const key = name + 中文;
  if (!canUpload(name)) throw new Error('denied');
  const store = new Store('root/');
  function nested() { const key = 'inner'; return key; }
  const callback = () => key;
  try {
    for (let i = 0; i < 2; i++) { handler(key); }
    store.put(key);
    nested(); callback();
    await Promise.resolve(key);
    return key;
  } finally { canUpload('cleanup'); }
}
export function recursive(n: number): number { return n ? recursive(n - 1) : 0; }
export function* generate() { yield 1; }
export const { left, right: alias } = {left: 1, right: 2};
export function scopes(input: {value: number}) {
  let key = input.value;
  { const key = 'shadow'; console.log(key); }
  key = 2; key += 1;
  const {value: alias} = input;
  return [key, alias];
}
export function multiline() {
  return canUpload(
    '中文😀'
  );
}
