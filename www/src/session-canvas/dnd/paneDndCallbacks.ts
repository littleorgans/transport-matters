import type { DragEndEvent, DragMoveEvent, DragStartEvent } from "@dnd-kit/core";
import { type EngineLayoutState, splicePaneOrder } from "../../engine";
import type { CanvasPaneRef } from "../model/paneRecords";
import { escapeDropLocator, resolvePasteHandle } from "../viewers/terminal/pasteRegistry";
import { locatorForPaneRef, paneIdAtWorldPoint } from "./canvasDrop";
import { pointerToWorld } from "./dndSpace";
import { clearDropTarget, setDropTarget, useDropTargetStore } from "./dropTargetStore";

// DndContext callbacks for the pane sortable (doc 19), the successor to the
// hand-rolled reorder controller. The store stays frozen during the drag: the
// callbacks write overlay feedback only, and a release either delivers a
// locator to a paste-handle pane (doc 14 precedence, order untouched) or
// commits the order once via movePaneOrder. dnd-kit owns activation, the
// over target, Escape cancellation, and the in-drag visuals.
export interface PaneDndDeps {
  getLayout(): EngineLayoutState;
  contentRefFor(paneId: string): CanvasPaneRef | undefined;
  titleFor(paneId: string): string;
  commitReorder(paneId: string, index: number): void;
  getSurfaceOrigin(): { left: number; top: number };
  // The expanded hero keeps a position in layout.order and stays a droppable
  // (so collision reports it as `over`), but it is delivery-only: a release
  // over it must never commit a reorder.
  getExpandedPaneId(): string | null;
}

export interface PaneDndResult {
  // True when the release changed something and the canvas should run one
  // settle window (paneMotion) so every pane springs to its new arrangement.
  settle: boolean;
}

// The one delivery resolution every consumer shares: collision (suppressing
// reorder targeting so the paste target does not shift away mid-hover), the
// move-tick highlight, and the release handler. A delivery target exists only
// when the dragged pane carries a locator AND the topmost pane under the
// point has a registered paste handle.
export function deliveryTargetAt(
  layout: EngineLayoutState,
  point: { x: number; y: number },
  activeId: string,
  contentRefFor: (paneId: string) => CanvasPaneRef | undefined,
): { targetPaneId: string; paste: (locator: string) => void } | null {
  if (locatorForPaneRef(contentRefFor(activeId)) === null) return null;
  const targetPaneId = paneIdAtWorldPoint(layout, point, activeId);
  if (targetPaneId === null) return null;
  const paste = resolvePasteHandle(targetPaneId);
  return paste === null ? null : { targetPaneId, paste };
}

export function createPaneDndCallbacks(deps: PaneDndDeps) {
  function dragWorldPoint(event: DragMoveEvent | DragEndEvent): { x: number; y: number } | null {
    const activator = event.activatorEvent as Partial<PointerEvent>;
    if (typeof activator.clientX !== "number" || typeof activator.clientY !== "number") {
      return null;
    }
    const origin = deps.getSurfaceOrigin();
    return pointerToWorld(deps.getLayout().viewport, {
      x: activator.clientX + event.delta.x - origin.left,
      y: activator.clientY + event.delta.y - origin.top,
    });
  }

  // Per-tick writes are change-guarded so a held pointer does not churn the
  // overlay store with identical terminal targets.
  function writeTerminalTarget(paneId: string | null): void {
    const current = useDropTargetStore.getState().target;
    if (paneId === null) {
      if (current !== null) clearDropTarget();
      return;
    }
    if (current?.kind === "terminal" && current.paneId === paneId) return;
    setDropTarget({ kind: "terminal", paneId, label: deps.titleFor(paneId) });
  }

  return {
    onDragStart(_event: DragStartEvent): void {
      clearDropTarget();
    },

    onDragMove(event: DragMoveEvent): void {
      const activeId = String(event.active.id);
      const point = dragWorldPoint(event);
      const terminal =
        point === null
          ? null
          : deliveryTargetAt(deps.getLayout(), point, activeId, deps.contentRefFor);
      writeTerminalTarget(terminal?.targetPaneId ?? null);
    },

    onDragEnd(event: DragEndEvent): PaneDndResult {
      const activeId = String(event.active.id);
      const layout = deps.getLayout();
      let settle = false;

      const locator = locatorForPaneRef(deps.contentRefFor(activeId));
      const point = dragWorldPoint(event);
      const terminal =
        point === null ? null : deliveryTargetAt(layout, point, activeId, deps.contentRefFor);

      const overId = event.over === null ? null : String(event.over.id);
      if (terminal && locator) {
        terminal.paste(escapeDropLocator(locator));
      } else if (overId !== null && overId !== activeId && overId !== deps.getExpandedPaneId()) {
        const index = layout.order.indexOf(overId);
        const spliced = index < 0 ? layout.order : splicePaneOrder(layout.order, activeId, index);
        if (spliced !== layout.order && !sameOrder(spliced, layout.order)) {
          deps.commitReorder(activeId, index);
          settle = true;
        }
      }

      clearDropTarget();
      return { settle };
    },

    onDragCancel(): PaneDndResult {
      clearDropTarget();
      // Nothing was committed mid-drag; the lifted pane's transform clears and
      // the settle window lets it spring home instead of snapping.
      return { settle: true };
    },
  };
}

function sameOrder(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((id, index) => id === b[index]);
}
