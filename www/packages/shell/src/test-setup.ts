import "@testing-library/jest-dom/vitest";

/**
 * Headless UI libraries (Ark UI / zag, used by the ⌘K command center) probe
 * `matchMedia` and call `scrollIntoView` on keyboard highlight. JSDOM ships
 * neither, so stub them with inert no-ops to keep portal/combobox renders from
 * throwing in tests.
 */
if (typeof window !== "undefined") {
  if (typeof window.matchMedia !== "function") {
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;
  }
  if (typeof Element.prototype.scrollIntoView !== "function") {
    Element.prototype.scrollIntoView = () => {};
  }
}

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
 * (getItem, setItem, removeItem). On Node 25, merely touching the getter can
 * also emit a `--localstorage-file` warning. Zustand's persist middleware
 * captures `localStorage` at module evaluation time, before jsdom can replace
 * it. Inspect the descriptor without dereferencing the getter, then install a
 * spec-compliant in-memory Storage so persist works in tests.
 */
const localStorageDescriptor = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
const shouldInstallMemoryStorage =
  !localStorageDescriptor ||
  typeof localStorageDescriptor.get === "function" ||
  typeof localStorageDescriptor.value?.setItem !== "function";

if (shouldInstallMemoryStorage) {
  const store = new Map<string, string>();
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    enumerable: true,
    writable: true,
    value: {
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
    },
  });
}
