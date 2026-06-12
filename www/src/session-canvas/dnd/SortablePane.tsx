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
  // Reactive per-pane lift disable (narrow selector): the expanded hero
  // never lifts, but it STAYS a droppable so collision reports it as `over`
  // and a release over it resolves to delivery-or-no-op instead of falling
  // through to the nearest side pane (paneDndCallbacks guards the commit).
  useLiftDisabled(paneId: string): boolean;
}

export function createSortablePaneAdapter(config: SortablePaneConfig): PaneDndAdapter {
  return function SortablePane({ paneId, children }) {
    const liftDisabled = config.useLiftDisabled(paneId);
    const { setNodeRef, listeners, transform, isDragging } = useSortable({
      id: paneId,
      disabled: { draggable: liftDisabled, droppable: false },
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
