export function permit(name: string) { return name.length > 0; }
export class Store {
  constructor(public prefix: string) {}
  put(key: string) { return this.prefix + key; }
}
