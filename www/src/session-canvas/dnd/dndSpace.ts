import type { ClientRect, CollisionDetection } from "@dnd-kit/core";
import type { Transform } from "@dnd-kit/utilities";
import type { CanvasViewport } from "../../engine";

// World-space geometry for the dnd-kit pane reorder (doc 19). dnd-kit never
// measures the DOM here: droppable AND draggable rects come straight from the
// planner store, the pointer converts screen -> world through the viewport,
// and rectSortingStrategy deltas therefore apply 1:1 inside the scaled world
// container. The draggable half of the measuring is load-bearing: with the
// library default, the active node's transform-stripped rect drifts under
// ancestor scale and dnd-kit's layout-shift compensation corrupts the drag
// delta nondeterministically toward delta/scale.

export interface DndWorldRectSource {
  nodes: Record<string, { rect: { x: number; y: number; width: number; height: number } }>;
}

// screen = world * scale + pan, so world = (screen - pan) / scale. `point` is
// relative to the canvas surface element, same convention as paneIdAtPoint.
export function pointerToWorld(
  viewport: CanvasViewport,
  point: { x: number; y: number },
): { x: number; y: number } {
  return {
    x: (point.x - viewport.panX) / viewport.scale,
    y: (point.y - viewport.panY) / viewport.scale,
  };
}

const ZERO_RECT: ClientRect = { top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 };

// Measure function for BOTH measuring.draggable and measuring.droppable: the
// pane's world rect from the store, as a plain object (dnd-kit's Rect wrapper
// reads own enumerable fields; a live DOMRect yields NaN rects).
export function createPlannerRectMeasure(
  getLayout: () => DndWorldRectSource,
): (element: HTMLElement) => ClientRect {
  return (element) => {
    const paneId = element.dataset.paneId;
    const rect = paneId === undefined ? undefined : getLayout().nodes[paneId]?.rect;
    if (rect === undefined) return { ...ZERO_RECT };
    return {
      top: rect.y,
      left: rect.x,
      right: rect.x + rect.width,
      bottom: rect.y + rect.height,
      width: rect.width,
      height: rect.height,
    };
  };
}

export interface WorldCollisionDeps {
  getViewport(): CanvasViewport;
  // The canvas surface element's client origin: dnd-kit reports pointer
  // coordinates in client space, the viewport transform is surface-relative.
  getSurfaceOrigin(): { left: number; top: number };
  // When the drag point sits on a delivery target (a locator pane over a
  // paste-handle pane), there is no reorder target at all: returning no
  // collisions clears `over`, the sortable strategy stops shifting siblings,
  // and the paste target stays put under the cursor instead of dodging it.
  getDeliveryTarget?(world: { x: number; y: number }, activeId: string): unknown | null;
}

// The shared pane-targeting core (doc 18): pointer-within first (the pane
// directly under the point wins, distance 0), closest rect center as the
// fallback so points over empty canvas still target the nearest slot. All
// comparisons happen in world coordinates. Consumed by the live-drag
// collision below and by the dock-drop index derivation (canvasDrop
// handleDockDrop), so dock drops and pane-drag reorders share one targeting
// feel.
export function closestPaneAtWorldPoint(
  orderedRects: ReadonlyArray<{
    id: string;
    rect: { x: number; y: number; width: number; height: number };
  }>,
  point: { x: number; y: number },
): { id: string; distance: number } | null {
  let closest: { id: string; distance: number } | null = null;
  for (const { id, rect } of orderedRects) {
    const inside =
      point.x >= rect.x &&
      point.x <= rect.x + rect.width &&
      point.y >= rect.y &&
      point.y <= rect.y + rect.height;
    if (inside) return { id, distance: 0 };
    const distance = Math.hypot(
      point.x - (rect.x + rect.width / 2),
      point.y - (rect.y + rect.height / 2),
    );
    if (closest === null || distance < closest.distance) {
      closest = { id, distance };
    }
  }
  return closest;
}

export function createWorldSpaceCollision(deps: WorldCollisionDeps): CollisionDetection {
  return ({ active, droppableContainers, droppableRects, pointerCoordinates }) => {
    if (pointerCoordinates === null) return [];
    const origin = deps.getSurfaceOrigin();
    const world = pointerToWorld(deps.getViewport(), {
      x: pointerCoordinates.x - origin.left,
      y: pointerCoordinates.y - origin.top,
    });
    if (active !== null && deps.getDeliveryTarget?.(world, String(active.id)) != null) {
      return [];
    }

    const entries: Array<{
      id: string;
      rect: { x: number; y: number; width: number; height: number };
    }> = [];
    for (const container of droppableContainers) {
      const rect = droppableRects.get(container.id);
      if (rect === undefined) continue;
      entries.push({
        id: String(container.id),
        rect: { x: rect.left, y: rect.top, width: rect.width, height: rect.height },
      });
    }
    const hit = closestPaneAtWorldPoint(entries, world);
    if (hit === null) return [];
    const container = droppableContainers.find((entry) => String(entry.id) === hit.id);
    return [{ id: hit.id, data: { droppableContainer: container, value: hit.distance } }];
  };
}

// The single conversion seam (doc 19). dnd-kit transforms are consumed raw,
// exactly once, here and nowhere else:
// - siblings: strategy deltas computed from world rects -> already world px.
// - active pane: the drag transform is a screen-space pointer delta -> divide
//   by the camera scale once. Invariant: applied * scale == raw. A skipped
//   conversion reads applied == raw; a doubled one reads applied == raw/scale².
export function sortableTransformToWorld(
  transform: Transform | null,
  worldScale: number,
  isDragging: boolean,
): { x: number; y: number } | null {
  if (transform === null) return null;
  if (!isDragging) return { x: transform.x, y: transform.y };
  return { x: transform.x / worldScale, y: transform.y / worldScale };
}
