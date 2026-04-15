import "@testing-library/jest-dom/vitest";

/**
 * JSDOM ships neither ResizeObserver nor layout. @tanstack/react-virtual
 * observes the scroll element via ResizeObserver and only renders items
 * once it gets a non-zero rect; without a shim virtualized lists render
 * nothing in tests. Fire once synchronously on observe() with a plausible
 * viewport so the virtualizer picks a visible range that covers the
 * fixtures.
 */
if (typeof globalThis.ResizeObserver === "undefined") {
  class MockResizeObserver {
    private readonly cb: ResizeObserverCallback;
    constructor(cb: ResizeObserverCallback) {
      this.cb = cb;
    }
    observe(target: Element): void {
      const rect: DOMRectReadOnly = {
        x: 0,
        y: 0,
        top: 0,
        left: 0,
        right: 1024,
        bottom: 800,
        width: 1024,
        height: 800,
        toJSON() {
          return this;
        },
      };
      const entry = {
        target,
        contentRect: rect,
        borderBoxSize: [{ inlineSize: 1024, blockSize: 800 }],
        contentBoxSize: [{ inlineSize: 1024, blockSize: 800 }],
        devicePixelContentBoxSize: [{ inlineSize: 1024, blockSize: 800 }],
      } as unknown as ResizeObserverEntry;
      this.cb([entry], this as unknown as ResizeObserver);
    }
    unobserve(): void {}
    disconnect(): void {}
  }
  globalThis.ResizeObserver = MockResizeObserver as unknown as typeof ResizeObserver;
}

/**
 * Node 22+ ships a built-in `localStorage` that lacks Web Storage API methods
 * (getItem, setItem, removeItem). Zustand's persist middleware captures
 * `localStorage` at module evaluation time, before jsdom can replace it. Provide
 * a spec-compliant in-memory Storage so persist works in tests.
 */
if (typeof globalThis.localStorage?.setItem !== "function") {
  const store = new Map<string, string>();
  globalThis.localStorage = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, value);
    },
    removeItem: (key: string) => {
      store.delete(key);
    },
    clear: () => {
      store.clear();
    },
    get length() {
      return store.size;
    },
    key: (index: number) => [...store.keys()][index] ?? null,
  };
}
