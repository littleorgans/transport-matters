import type { PaneId } from "../../engine";
import type { CanvasPaneRef } from "../model/paneRecords";

// Same-window holder for the in-flight dock-row drag (doc 18). The HTML5 data
// store is in protected mode during dragover (types readable, payload not),
// so the dragover resolver consults this module-scoped singleton to learn the
// dragged ref synchronously and honor decision 3 (non-locator refs never
// target a terminal). Mirrors the existing module-scoped drag singletons
// pasteRegistry and dropTargetStore: drags span React trees. The drop handler
// reads the authoritative payload from the mime instead; cross-window drags
// carry the mime but have no holder, and resolve as surface drops.
export const PANE_REF_MIME = "application/x-tm-pane-ref";

export interface DockDragEntry {
  paneId: PaneId;
  ref: CanvasPaneRef | null;
}

let active: DockDragEntry | null = null;

export function setActiveDockDrag(entry: DockDragEntry): void {
  active = entry;
}

export function clearActiveDockDrag(): void {
  active = null;
}

export function readActiveDockDrag(): DockDragEntry | null {
  return active;
}

// Drop-time parse of the authoritative mime payload (the data store leaves
// protected mode on drop). Cross-window or hostile payloads resolve to null
// rather than throwing; the ref is trusted as-is, the same posture as the
// uri-list path.
export function parseDockDragPayload(json: string): DockDragEntry | null {
  if (json.length === 0) return null;
  try {
    const parsed: unknown = JSON.parse(json);
    if (typeof parsed !== "object" || parsed === null) return null;
    const entry = parsed as Partial<DockDragEntry>;
    if (typeof entry.paneId !== "string") return null;
    return { paneId: entry.paneId, ref: entry.ref ?? null };
  } catch {
    return null;
  }
}
