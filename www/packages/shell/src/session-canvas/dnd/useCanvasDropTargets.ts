import { canResolveDroppedFiles, getDroppedFilePathResolver } from "@tm/core";
import { type RefObject, useCallback, useEffect, useRef, useState } from "react";
import type { EngineLayoutState } from "../../engine";
import type { CanvasPaneRef, PaneContentRef } from "../model/paneRecords";
import { resolvePasteHandle } from "../viewers/terminal/pasteRegistry";
import { handleCanvasDrop, handleDockDrop, locatorForPaneRef, paneIdAtPoint } from "./canvasDrop";
import {
  clearActiveDockDrag,
  PANE_REF_MIME,
  parseDockDragPayload,
  readActiveDockDrag,
} from "./dockDragSource";
import { clearDropTarget, setDropTarget } from "./dropTargetStore";

// Shared drop wiring for every canvas surface (/canvas CanvasSurface and the
// /canvas-lab stage): intercepts dragover/drop on the surface element (the
// browser default for a dropped file is navigation, which destroys the canvas),
// routes drops through handleCanvasDrop (external) or handleDockDrop (dock
// rows, doc 18), and exposes the pane-release hook for pane-onto-terminal
// delivery. Store specifics arrive as injected deps so both stores share one
// path instead of copying the listeners.

export interface CanvasDropTargetDeps {
  getLayout(): EngineLayoutState;
  contentRefFor(paneId: string): CanvasPaneRef | undefined;
  titleFor(paneId: string): string;
  spawnPane(ref: PaneContentRef, options?: { focus: boolean }): string;
  dockPane(ref: PaneContentRef): string;
  // Dock drag-out: restore the docked pane at the order slot the drop chose.
  restorePaneAtIndex(paneId: string, index: number): void;
}

export function useCanvasDropTargets(
  surfaceRef: RefObject<HTMLElement | null>,
  deps: CanvasDropTargetDeps,
) {
  const [dropHint, setDropHint] = useState<string | null>(null);
  // Listeners mount once per surface; reads go through the ref so re-renders
  // never re-subscribe (same pattern as terminalSession's callback refs).
  const depsRef = useRef(deps);
  depsRef.current = deps;

  useEffect(() => {
    const surface = surfaceRef.current;
    if (!surface) return;

    const onDragOver = (event: DragEvent) => {
      event.preventDefault();
      const rect = surface.getBoundingClientRect();
      const current = depsRef.current;
      const point = { x: event.clientX - rect.left, y: event.clientY - rect.top };
      const layout = current.getLayout();

      if (event.dataTransfer !== null && dataTransferHasPaneRef(event.dataTransfer)) {
        // Dock drag (doc 18). The payload is unreadable in dragover protected
        // mode, so the holder stands in: a locator-bearing entry over a
        // paste-handle pane is a paste (copy), anything else restores here
        // (move). Never `hint`: a dock entry is already resolved in memory,
        // in the plain browser too.
        const locator = locatorForPaneRef(readActiveDockDrag()?.ref);
        const targetPaneId = locator === null ? null : paneIdAtPoint(layout, point);
        const paste = targetPaneId === null ? null : resolvePasteHandle(targetPaneId);
        if (targetPaneId !== null && paste !== null) {
          event.dataTransfer.dropEffect = "copy";
          setDropTarget({
            kind: "terminal",
            paneId: targetPaneId,
            label: current.titleFor(targetPaneId),
          });
        } else {
          event.dataTransfer.dropEffect = "move";
          setDropTarget({ kind: "surface" });
        }
        return;
      }

      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
      const targetPaneId = paneIdAtPoint(layout, point);
      const paste = targetPaneId === null ? null : resolvePasteHandle(targetPaneId);
      if (targetPaneId !== null && paste !== null) {
        setDropTarget({
          kind: "terminal",
          paneId: targetPaneId,
          label: current.titleFor(targetPaneId),
        });
      } else if (
        event.dataTransfer !== null &&
        dataTransferHasFiles(event.dataTransfer) &&
        !canResolveDroppedFiles()
      ) {
        setDropTarget({ kind: "hint" });
      } else {
        setDropTarget({ kind: "surface" });
      }
    };
    const onDragLeave = () => {
      clearDropTarget();
    };
    const onDrop = (event: DragEvent) => {
      event.preventDefault();
      clearDropTarget();
      if (!event.dataTransfer) return;
      const rect = surface.getBoundingClientRect();
      const current = depsRef.current;
      const point = { x: event.clientX - rect.left, y: event.clientY - rect.top };

      if (dataTransferHasPaneRef(event.dataTransfer)) {
        // Same dispatch as dragover; the drop reads the authoritative payload
        // (the data store is in read mode now). A pane-ref drop never falls
        // through to the external pipeline: an unparseable payload is a no-op,
        // the entry simply stays docked.
        clearActiveDockDrag();
        const payload = parseDockDragPayload(event.dataTransfer.getData(PANE_REF_MIME));
        if (payload !== null) {
          handleDockDrop(current.getLayout(), point, payload, {
            dockPane: current.dockPane,
            restorePaneAtIndex: current.restorePaneAtIndex,
          });
        }
        return;
      }

      handleCanvasDrop(current.getLayout(), point, event.dataTransfer, {
        resolvePath: getDroppedFilePathResolver(),
        spawnPane: current.spawnPane,
        dockPane: current.dockPane,
        showHint: setDropHint,
      });
    };

    surface.addEventListener("dragover", onDragOver);
    surface.addEventListener("dragleave", onDragLeave);
    surface.addEventListener("drop", onDrop);
    return () => {
      surface.removeEventListener("dragover", onDragOver);
      surface.removeEventListener("dragleave", onDragLeave);
      surface.removeEventListener("drop", onDrop);
    };
  }, [surfaceRef]);

  const dismissDropHint = useCallback(() => setDropHint(null), []);

  return { dropHint, dismissDropHint };
}

function dataTransferHasFiles(transfer: DataTransfer): boolean {
  return Array.from(transfer.types).includes("Files");
}

// The kind dispatch (doc 18): both drag kinds expose their KIND through
// `types` during protected mode, neither exposes its payload until drop.
function dataTransferHasPaneRef(transfer: DataTransfer): boolean {
  return Array.from(transfer.types).includes(PANE_REF_MIME);
}
