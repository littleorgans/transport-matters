import { type EngineLayoutState, splicePaneOrder, type WorldRect } from "../../engine";
import { insertionIndexAtWorldPoint, type OrderedRect } from "../../engine/layout";
import type { CanvasPaneRef } from "../model/paneRecords";
import { escapeDropLocator, resolvePasteHandle } from "../viewers/terminal/pasteRegistry";
import { paneIdAtWorldPoint } from "./canvasDrop";
import { clearDropTarget, setDropTarget } from "./dropTargetStore";

// Surface-side reorder controller (one per canvas surface, store-agnostic):
// move ticks compute the insertion index against the OTHER open panes and
// preview on change; release delivers to a paste-handle pane (locator refs,
// doc 14 precedence) or commits the order; escape cancels. Spec doc 17.
export interface PaneReorderDeps {
  getLayout(): EngineLayoutState;
  contentRefFor(paneId: string): CanvasPaneRef | undefined;
  titleFor(paneId: string): string;
  previewReorder(paneId: string, index: number): void;
  commitReorder(paneId: string, index: number): void;
  cancelReorder(): void;
}

export function createPaneReorder(deps: PaneReorderDeps) {
  let lifted: string | null = null;
  let lastIndex: number | null = null;
  let previewed = false;

  const center = (rect: WorldRect) => ({
    x: rect.x + rect.width / 2,
    y: rect.y + rect.height / 2,
  });

  // The committed order never changes mid-drag (previews are tentative), so
  // comparing the spliced order against it detects "the pane is in its own
  // slot": zero-move clicks stay inert, drag-back-home cancels, not commits.
  const sameOrder = (a: readonly string[], b: readonly string[]) =>
    a.length === b.length && a.every((id, i) => id === b[i]);

  function otherOpenRects(layout: EngineLayoutState, excludePaneId: string): OrderedRect[] {
    return layout.order
      .filter((id) => id !== excludePaneId && layout.nodes[id]?.lifecycle === "open")
      .map((id) => ({ paneId: id, rect: (layout.nodes[id] as { rect: WorldRect }).rect }));
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

  return {
    isActive: () => lifted !== null,

    onMove(paneId: string, rect: WorldRect): void {
      lifted = paneId;
      const layout = deps.getLayout();
      const point = center(rect);

      const terminal = locatorFor(paneId) === null ? null : terminalUnder(layout, point);
      if (terminal) {
        setDropTarget({
          kind: "terminal",
          paneId: terminal.targetPaneId,
          label: deps.titleFor(terminal.targetPaneId),
        });
      } else {
        clearDropTarget();
      }

      const index = insertionIndexAtWorldPoint(otherOpenRects(layout, paneId), point);
      if (index !== lastIndex) {
        lastIndex = index;
        const changesOrder = !sameOrder(splicePaneOrder(layout.order, paneId, index), layout.order);
        // Preview on a real change, or to restore the committed arrangement
        // after earlier previews; never on the inert first tick of a click.
        if (changesOrder || previewed) {
          previewed = true;
          deps.previewReorder(paneId, index);
        }
      }
    },

    onMoveEnd(paneId: string, rect: WorldRect): void {
      const layout = deps.getLayout();
      const locator = locatorFor(paneId);
      const terminal = locator === null ? null : terminalUnder(layout, center(rect));
      if (terminal && locator) {
        terminal.paste(escapeDropLocator(locator));
        deps.cancelReorder();
      } else if (
        lastIndex !== null &&
        !sameOrder(splicePaneOrder(layout.order, paneId, lastIndex), layout.order)
      ) {
        deps.commitReorder(paneId, lastIndex);
      } else if (previewed) {
        deps.cancelReorder();
      }
      lifted = null;
      lastIndex = null;
      previewed = false;
      clearDropTarget();
    },

    onCancel(_paneId: string): void {
      deps.cancelReorder();
      lifted = null;
      lastIndex = null;
      previewed = false;
      clearDropTarget();
    },
  };
}
