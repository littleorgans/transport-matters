import "@testing-library/jest-dom/vitest";

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
