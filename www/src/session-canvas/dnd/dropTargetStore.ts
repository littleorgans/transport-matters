import { create } from "zustand";
import type { WorldRect } from "../../engine";

// One active drop target for the whole canvas, written by both drag systems
// (HTML5 dragover for external/dock drags, pane-lift move ticks) and read by
// CanvasDropTargetOverlay. Module-scoped like pasteRegistry: drags span trees.
export type DropTarget =
  | { kind: "surface" }
  | { kind: "hint" }
  | { kind: "slot"; rect: WorldRect }
  | { kind: "terminal"; paneId: string; label: string };

interface DropTargetState {
  target: DropTarget | null;
}

export const useDropTargetStore = create<DropTargetState>(() => ({ target: null }));

export function setDropTarget(target: DropTarget): void {
  useDropTargetStore.setState({ target });
}

export function clearDropTarget(): void {
  useDropTargetStore.setState({ target: null });
}
