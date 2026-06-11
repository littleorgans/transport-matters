// Terminal-backed panes register a paste handle here so the canvas-root drop
// handler can deliver a locator to the hit pane without reaching into xterm.
// Module-scoped on purpose: registration spans stores and React trees.
export interface DropLocator {
  source: "path" | "url";
  locator: string;
}

type PasteHandle = (text: string) => void;

const handles = new Map<string, PasteHandle>();

export function registerPasteHandle(paneId: string, paste: PasteHandle): () => void {
  handles.set(paneId, paste);
  return () => {
    if (handles.get(paneId) === paste) handles.delete(paneId);
  };
}

export function resolvePasteHandle(paneId: string): PasteHandle | null {
  return handles.get(paneId) ?? null;
}

const SHELL_UNSAFE = /[ \t'"\\`$&;|<>(){}[\]*?#~!]/g;

export function escapeDropLocator(locator: DropLocator): string {
  if (locator.source === "url") return locator.locator;
  return locator.locator.replace(SHELL_UNSAFE, (char) => `\\${char}`);
}
