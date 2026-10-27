export function canUpload(user: { enabled: boolean }): boolean {
  return user.enabled;
}

export function createKey(name: string): string {
  return `asset/${name}`;
}

export class Store {
  constructor() {}

  put(key: string, value: unknown): string {
    return key;
  }
}
