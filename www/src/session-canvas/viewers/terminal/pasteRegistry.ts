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
// C0 controls + DEL. A raw newline in a pasted locator submits whatever
// follows to the foreground program (bracketed paste is not guaranteed), so a
// hostile file name becomes command injection. Stripped outright: a path that
// needed control characters was never safely pasteable anyway.
// biome-ignore lint/suspicious/noControlCharactersInRegex: matching control characters is the point; they are stripped before any locator reaches a PTY.
const CONTROL_CHARS = /[\u0000-\u001f\u007f]/g;

export function escapeDropLocator(locator: DropLocator): string {
  const sanitized = locator.locator.replace(CONTROL_CHARS, "");
  if (locator.source === "url") return sanitized;
  return sanitized.replace(SHELL_UNSAFE, (char) => `\\${char}`);
}
