import { absent } from './dependency-that-is-not-present';
export function missingDependency() {
  return absent();
}
