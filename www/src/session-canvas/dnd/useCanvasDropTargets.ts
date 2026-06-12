import { type RefObject, useCallback, useEffect, useRef, useState } from "react";
import type { EngineLayoutState } from "../../engine";
import type { CanvasPaneRef, PaneContentRef } from "../model/paneRecords";
import { resolvePasteHandle } from "../viewers/terminal/pasteRegistry";
import { handleCanvasDrop, paneIdAtPoint } from "./canvasDrop";
import { clearDropTarget, setDropTarget } from "./dropTargetStore";

// Shared drop wiring for every canvas surface (/canvas CanvasSurface and the
// /canvas-lab stage): intercepts dragover/drop on the surface element (the
// browser default for a dropped file is navigation, which destroys the canvas),
// routes drops through handleCanvasDrop, and exposes the pane-release hook for
// pane-onto-terminal delivery. Store specifics arrive as injected deps so both
// stores share one path instead of copying the listeners.

export interface CanvasDropTargetDeps {
  getLayout(): EngineLayoutState;
  contentRefFor(paneId: string): CanvasPaneRef | undefined;
  titleFor(paneId: string): string;
  spawnPane(ref: PaneContentRef, options?: { focus: boolean }): string;
  minimizePane(paneId: string): void;
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
      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
      const rect = surface.getBoundingClientRect();
      const current = depsRef.current;
      const point = { x: event.clientX - rect.left, y: event.clientY - rect.top };
      const layout = current.getLayout();
      const targetPaneId = paneIdAtPoint(layout, point);
      const paste = targetPaneId === null ? null : resolvePasteHandle(targetPaneId);
      if (targetPaneId !== null && paste !== null) {
        setDropTarget({
          kind: "terminal",
          paneId: targetPaneId,
          label: current.titleFor(targetPaneId),
        });
      } else if (
        event.dataTransfer?.files.length &&
        !window.transportMattersDesktop?.getPathForFile
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
      handleCanvasDrop(
        current.getLayout(),
        { x: event.clientX - rect.left, y: event.clientY - rect.top },
        event.dataTransfer,
        {
          resolvePath: window.transportMattersDesktop?.getPathForFile ?? null,
          spawnPane: current.spawnPane,
          minimizePane: current.minimizePane,
          showHint: setDropHint,
        },
      );
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
