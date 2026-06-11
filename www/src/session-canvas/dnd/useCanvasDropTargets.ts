import { type RefObject, useCallback, useEffect, useRef, useState } from "react";
import type { EngineLayoutState, WorldRect } from "../../engine";
import type { CanvasPaneRef, PaneContentRef } from "../model/paneRecords";
import { deliverPaneDropToTerminal, handleCanvasDrop } from "./canvasDrop";

// Shared drop wiring for every canvas surface (/canvas CanvasSurface and the
// /canvas-lab stage): intercepts dragover/drop on the surface element (the
// browser default for a dropped file is navigation, which destroys the canvas),
// routes drops through handleCanvasDrop, and exposes the pane-release hook for
// pane-onto-terminal delivery. Store specifics arrive as injected deps so both
// stores share one path instead of copying the listeners.

export interface CanvasDropTargetDeps {
  getLayout(): EngineLayoutState;
  contentRefFor(paneId: string): CanvasPaneRef | undefined;
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
    };
    const onDrop = (event: DragEvent) => {
      event.preventDefault();
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
    surface.addEventListener("drop", onDrop);
    return () => {
      surface.removeEventListener("dragover", onDragOver);
      surface.removeEventListener("drop", onDrop);
    };
  }, [surfaceRef]);

  /** Wire to LayoutCanvas onMovePaneEnd: a released locator pane over a terminal pastes. */
  const onMovePaneEnd = useCallback((paneId: string, rect: WorldRect) => {
    const current = depsRef.current;
    deliverPaneDropToTerminal(current.getLayout(), current.contentRefFor(paneId), paneId, rect);
  }, []);

  const dismissDropHint = useCallback(() => setDropHint(null), []);

  return { dropHint, dismissDropHint, onMovePaneEnd };
}
