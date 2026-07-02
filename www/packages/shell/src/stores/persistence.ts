/**
 * Inspector-owned localStorage key registry plus dismissed-panel helpers.
 * The canvas keeps its own registry in `session-canvas/persistence/
 * storageKeys.ts`; both products share one origin, so a shell-level test
 * asserts the two registries never collide.
 */
export const INSPECTOR_STORAGE_KEYS = {
  uiStore: "transport-matters-ui",
  overlaysStore: "transport-matters-overlays",
  dismissedPanelPrefix: "transport-matters.panel.dismissed.",
} as const;

function getAvailableStorage(): Storage | null {
  try {
    return globalThis.localStorage;
  } catch {
    return null;
  }
}

export function dismissedPanelKey(id: string): string {
  return `${INSPECTOR_STORAGE_KEYS.dismissedPanelPrefix}${id}`;
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
