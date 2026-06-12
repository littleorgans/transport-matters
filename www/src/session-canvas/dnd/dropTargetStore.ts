import { create } from "zustand";

// One active drop target for the whole canvas, written by both drag systems
// (HTML5 dragover for external/dock drags, pane-lift move ticks) and read by
// CanvasDropTargetOverlay. Module-scoped like pasteRegistry: drags span trees.
// Pane reorder needs no slot indicator: the sortable sibling shift IS the
// insertion feedback (doc 19 amendment to doc 17 decision 2).
export type DropTarget =
  | { kind: "surface" }
  | { kind: "hint" }
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
