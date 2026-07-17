import "@testing-library/jest-dom/vitest";

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
