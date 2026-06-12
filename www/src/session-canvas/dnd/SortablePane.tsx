import { useSortable } from "@dnd-kit/sortable";
import type { PaneDndAdapter } from "../../engine";
import { sortableTransformToWorld } from "./dndSpace";

// Per-pane useSortable adapter (doc 19): keeps the engine dnd-kit-free by
// handing PaneFrame a plain prop bundle. The transform crosses the
// sortableTransformToWorld seam here, so PaneFrame consumes world pixels and
// applies them 1:1 inside the scaled world container.
export interface SortablePaneConfig {
  // Read non-reactively: the scale is only consumed while this pane drags,
  // every drag tick re-renders the pane through its transform, and zoom is
  // locked for the drag's duration (LayoutCanvas zoomLocked).
  readWorldScale(): number;
  // Reactive per-pane disable (narrow selector): the expanded hero never
  // lifts and never collides; it stays a delivery target through the store
  // hit-test in paneDndCallbacks.
  useSortableDisabled(paneId: string): boolean;
}

export function createSortablePaneAdapter(config: SortablePaneConfig): PaneDndAdapter {
  return function SortablePane({ paneId, children }) {
    const disabled = config.useSortableDisabled(paneId);
    const { setNodeRef, listeners, transform, isDragging } = useSortable({
      id: paneId,
      disabled: { draggable: disabled, droppable: disabled },
    });
    return children({
      setNodeRef,
      listeners: listeners as React.HTMLAttributes<HTMLElement> | undefined,
      transform: sortableTransformToWorld(
        transform,
        isDragging ? config.readWorldScale() : 1,
        isDragging,
      ),
      isDragging,
    });
  };
}
