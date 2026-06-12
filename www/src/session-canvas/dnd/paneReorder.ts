import { type EngineLayoutState, splicePaneOrder, type WorldRect } from "../../engine";
import {
  insertionIndexAtWorldPoint,
  insertionSlotRect,
  type OrderedRect,
} from "../../engine/layout";
import type { CanvasPaneRef } from "../model/paneRecords";
import { escapeDropLocator, resolvePasteHandle } from "../viewers/terminal/pasteRegistry";
import { paneIdAtWorldPoint } from "./canvasDrop";
import { clearDropTarget, setDropTarget } from "./dropTargetStore";

const REORDER_START_THRESHOLD_WORLD_PX = 4;

// Surface-side reorder controller (one per canvas surface, store-agnostic):
// move ticks compute the insertion index against the OTHER open panes and
// write slot or terminal feedback only; release delivers to a paste-handle
// pane (locator refs, doc 14 precedence) or commits the order; escape
// cancels. Spec doc 17.
export interface PaneReorderDeps {
  getLayout(): EngineLayoutState;
  contentRefFor(paneId: string): CanvasPaneRef | undefined;
  titleFor(paneId: string): string;
  commitReorder(paneId: string, index: number): void;
  cancelReorder(): void;
}

export function createPaneReorder(deps: PaneReorderDeps) {
  let lifted: string | null = null;
  let liftOrigin: WorldRect | null = null;
  let insertionRects: OrderedRect[] | null = null;
  let reorderActive = false;

  const center = (rect: WorldRect) => ({
    x: rect.x + rect.width / 2,
    y: rect.y + rect.height / 2,
  });

  // The committed order never changes mid-drag, so comparing the spliced
  // order against it detects "the pane is in its own slot": zero-move clicks
  // stay inert, drag-back-home is a no-op, not a replan.
  const sameOrder = (a: readonly string[], b: readonly string[]) =>
    a.length === b.length && a.every((id, i) => id === b[i]);

  function otherOpenRects(layout: EngineLayoutState, excludePaneId: string): OrderedRect[] {
    return layout.order
      .filter((id) => id !== excludePaneId && layout.nodes[id]?.lifecycle === "open")
      .map((id) => ({ paneId: id, rect: (layout.nodes[id] as { rect: WorldRect }).rect }));
  }

  function samePaneIdSet(a: readonly OrderedRect[], b: readonly OrderedRect[]): boolean {
    if (a.length !== b.length) return false;
    const ids = new Set(a.map((entry) => entry.paneId));
    return b.every((entry) => ids.has(entry.paneId));
  }

  function insertionCandidates(layout: EngineLayoutState, paneId: string): OrderedRect[] {
    const current = otherOpenRects(layout, paneId);
    if (insertionRects === null || !samePaneIdSet(insertionRects, current)) {
      insertionRects = current;
    }
    return insertionRects;
  }

  function locatorFor(paneId: string): { source: "path" | "url"; locator: string } | null {
    const ref = deps.contentRefFor(paneId);
    if (ref === undefined || ref.kind !== "resource" || !("source" in ref)) return null;
    return ref.source === "path"
      ? { source: "path", locator: ref.path }
      : { source: "url", locator: ref.url };
  }

  function terminalUnder(layout: EngineLayoutState, point: { x: number; y: number }) {
    const targetPaneId = lifted === null ? null : paneIdAtWorldPoint(layout, point, lifted);
    if (targetPaneId === null) return null;
    const paste = resolvePasteHandle(targetPaneId);
    return paste === null ? null : { targetPaneId, paste };
  }

  function resetLift(): void {
    lifted = null;
    liftOrigin = null;
    insertionRects = null;
    reorderActive = false;
  }

  function startLift(paneId: string, rect: WorldRect): void {
    lifted = paneId;
    liftOrigin = rect;
    insertionRects = otherOpenRects(deps.getLayout(), paneId);
    reorderActive = false;
  }

  function movedBeyondThreshold(rect: WorldRect): boolean {
    if (liftOrigin === null) return false;
    const dx = rect.x - liftOrigin.x;
    const dy = rect.y - liftOrigin.y;
    return Math.hypot(dx, dy) > REORDER_START_THRESHOLD_WORLD_PX;
  }

  return {
    isActive: () => reorderActive,

    onMove(paneId: string, rect: WorldRect): void {
      if (lifted !== paneId) startLift(paneId, rect);
      if (!reorderActive) {
        if (!movedBeyondThreshold(rect)) return;
        reorderActive = true;
      }
      const layout = deps.getLayout();
      const point = center(rect);

      const terminal = locatorFor(paneId) === null ? null : terminalUnder(layout, point);
      if (terminal) {
        setDropTarget({
          kind: "terminal",
          paneId: terminal.targetPaneId,
          label: deps.titleFor(terminal.targetPaneId),
        });
        return;
      }

      const candidates = insertionCandidates(layout, paneId);
      const index = insertionIndexAtWorldPoint(candidates, point);
      const slot = insertionSlotRect(candidates, index, point, rect);
      setDropTarget({ kind: "slot", rect: slot });
    },

    onMoveEnd(paneId: string, rect: WorldRect) {
      if (!reorderActive) {
        resetLift();
        clearDropTarget();
        return { settle: false };
      }
      const layout = deps.getLayout();
      const locator = locatorFor(paneId);
      const terminal = locator === null ? null : terminalUnder(layout, center(rect));
      const releaseIndex = insertionIndexAtWorldPoint(
        insertionCandidates(layout, paneId),
        center(rect),
      );
      let settle = false;
      if (terminal && locator) {
        terminal.paste(escapeDropLocator(locator));
      } else if (!sameOrder(splicePaneOrder(layout.order, paneId, releaseIndex), layout.order)) {
        deps.commitReorder(paneId, releaseIndex);
        settle = true;
      }
      resetLift();
      clearDropTarget();
      return { settle };
    },

    onCancel(_paneId: string) {
      const settle = reorderActive;
      if (settle) deps.cancelReorder();
      resetLift();
      clearDropTarget();
      return { settle };
    },
  };
}
