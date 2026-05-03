import { createJSONStorage, type PersistStorage, type StateStorage } from "zustand/middleware";

export const FRONTEND_STORAGE_KEYS = {
  uiStore: "manicure-ui",
  overlaysStore: "manicure-overlays",
  dismissedPanelPrefix: "manicure.panel.dismissed.",
} as const;

function getBrowserStorage(): StateStorage {
  return globalThis.localStorage;
}

function getAvailableStorage(): Storage | null {
  try {
    return globalThis.localStorage;
  } catch {
    return null;
  }
}

export function createFrontendPersistStorage<S>(): PersistStorage<S> | undefined {
  return createJSONStorage<S>(getBrowserStorage);
}

export function dismissedPanelKey(id: string): string {
  return `${FRONTEND_STORAGE_KEYS.dismissedPanelPrefix}${id}`;
}

export function hasDismissedPanel(id: string): boolean {
  const storage = getAvailableStorage();
  if (!storage) return false;
  try {
    return storage.getItem(dismissedPanelKey(id)) === "1";
  } catch {
    return false;
  }
}

export function markPanelDismissed(id: string): void {
  const storage = getAvailableStorage();
  if (!storage) return;
  try {
    storage.setItem(dismissedPanelKey(id), "1");
  } catch {
    // Quota exhausted or disallowed. Silently give up. Worst case, the
    // panel reappears next load; better than crashing the editor.
  }
}
