import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(cleanup);

class TestStorage implements Storage {
  private values = new Map<string, string>();
  get length() { return this.values.size; }
  clear() { this.values.clear(); }
  getItem(key: string) { return this.values.get(key) ?? null; }
  key(index: number) { return [...this.values.keys()][index] ?? null; }
  removeItem(key: string) { this.values.delete(key); }
  setItem(key: string, value: string) { this.values.set(key, String(value)); }
}

if (!globalThis.window.localStorage) {
  Object.defineProperty(globalThis.window, "localStorage", { value: new TestStorage(), configurable: true });
}

class TestResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

Object.defineProperty(globalThis, "ResizeObserver", { value: TestResizeObserver, configurable: true });
Object.defineProperty(globalThis.Range.prototype, "getClientRects", {
  value: () => ({ length: 0, item: () => null, [Symbol.iterator]: function* iterator() {} }),
  configurable: true,
});
Object.defineProperty(globalThis.Range.prototype, "getBoundingClientRect", {
  value: () => ({ x: 0, y: 0, width: 0, height: 0, top: 0, right: 0, bottom: 0, left: 0, toJSON: () => ({}) }),
  configurable: true,
});
