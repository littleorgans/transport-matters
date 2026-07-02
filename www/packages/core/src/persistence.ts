import { createJSONStorage, type PersistStorage, type StateStorage } from "zustand/middleware";

function getBrowserStorage(): StateStorage {
  return globalThis.localStorage;
}

/**
 * JSON-serializing zustand persist storage over `localStorage`, resolved
 * lazily so store modules can be imported in non-browser contexts. Each
 * product owns its storage keys; this helper only owns the mechanism.
 */
export function createFrontendPersistStorage<S>(): PersistStorage<S> | undefined {
  return createJSONStorage<S>(getBrowserStorage);
}
