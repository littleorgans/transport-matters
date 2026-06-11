import { useCallback, useEffect, useRef, useState } from "react";
import { LayoutCanvas, type PaneId, type WorldRect } from "../../engine";
import type { LaunchResolutionStatus } from "../api/launchResolution";
import { deliverPaneDropToTerminal, handleCanvasDrop } from "../dnd/canvasDrop";
import { useCanvasStore } from "../model/canvasStore";
import type { CanvasLaunchContext } from "../route";
import { PICKER_PANE_ID, renderPaneContent } from "../viewers/registry";
import { CanvasCommandBar } from "./CanvasCommandBar";
import { CanvasDropHint } from "./CanvasDropHint";
import { PaneDock } from "./PaneDock";
import { PaneWindow } from "./PaneWindow";

export interface CanvasSurfaceProps {
  launch: CanvasLaunchContext;
  launchStatus: LaunchResolutionStatus;
  launchSessionId: string | null;
}

export function CanvasSurface({ launch, launchStatus, launchSessionId }: CanvasSurfaceProps) {
  const layout = useCanvasStore((state) => state.layout);
  const panes = useCanvasStore((state) => state.panes);
  const canvasId = useCanvasStore((state) => state.id);
  const workspaceHash = useCanvasStore((state) => state.workspaceHash);
  const focusPane = useCanvasStore((state) => state.focusPane);
  const closePane = useCanvasStore((state) => state.closePane);
  const closeDockedPane = useCanvasStore((state) => state.closeDockedPane);
  const docked = useCanvasStore((state) => state.docked);
  const expandedPaneId = useCanvasStore((state) => state.expandedPaneId);
  const framedPaneId = useCanvasStore((state) => state.framing.paneId);
  const expandPane = useCanvasStore((state) => state.expandPane);
  const framePane = useCanvasStore((state) => state.framePane);
  const minimizePane = useCanvasStore((state) => state.minimizePane);
  const movePane = useCanvasStore((state) => state.movePane);
  const spawnPane = useCanvasStore((state) => state.spawnPane);
  const resizePane = useCanvasStore((state) => state.resizePane);
  const restorePane = useCanvasStore((state) => state.restorePane);
  const setBounds = useCanvasStore((state) => state.setBounds);
  const setViewport = useCanvasStore((state) => state.setViewport);
  const resetViewport = useCanvasStore((state) => state.resetViewport);
  const spawnOrFocusTranscript = useCanvasStore((state) => state.spawnOrFocusTranscript);
  const surfaceRef = useRef<HTMLElement>(null);
  const [dropHint, setDropHint] = useState<string | null>(null);
  const focusedPaneId = layout.focusedPaneId;
  const focusedTitle = focusedPaneId ? (panes[focusedPaneId]?.title ?? null) : null;

  useEffect(() => {
    const element = surfaceRef.current;
    if (!element) return;
    const measure = () => {
      const bounds = { width: element.clientWidth, height: element.clientHeight };
      if (bounds.width > 0 && bounds.height > 0) setBounds(bounds);
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [setBounds]);

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
      handleCanvasDrop(
        useCanvasStore.getState().layout,
        { x: event.clientX - rect.left, y: event.clientY - rect.top },
        event.dataTransfer,
        {
          resolvePath: window.transportMattersDesktop?.getPathForFile ?? null,
          spawnPane,
          minimizePane,
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
  }, [spawnPane, minimizePane]);

  const onMovePaneEnd = useCallback((paneId: PaneId, rect: WorldRect) => {
    const state = useCanvasStore.getState();
    deliverPaneDropToTerminal(state.layout, state.panes[paneId]?.contentRef, paneId, rect);
  }, []);

  // Stable across viewport-only renders so the memoized PaneLayer skips the pane subtree on pan/zoom.
  // Re-created only when the data it reads changes (panes, focus, actions, launch context).
  const renderPane = useCallback(
    (paneId: string) => {
      const pane = panes[paneId];
      if (!pane) return null;
      const titleId = titleIdForPane(paneId);
      const content = renderPaneContent({
        pane,
        actions: { closePane, focusPane, spawnOrFocusTranscript },
        canvas: {
          id: canvasId,
          owner: "local",
          workspaceHash,
          focusedPaneId,
          launch,
          launchStatus,
          launchSessionId,
        },
      });
      return (
        <PaneWindow
          expanded={expandedPaneId === paneId}
          framed={framedPaneId === paneId}
          focused={focusedPaneId === paneId}
          onClose={() => closePane(paneId)}
          onExpand={() => expandPane(paneId)}
          onFrame={() => framePane(paneId)}
          onHeaderDoubleClick={(event) => (event.shiftKey ? expandPane(paneId) : framePane(paneId))}
          onMinimize={() => minimizePane(paneId)}
          pane={pane}
          titleId={titleId}
        >
          {content}
        </PaneWindow>
      );
    },
    [
      panes,
      closePane,
      expandPane,
      expandedPaneId,
      framePane,
      framedPaneId,
      focusPane,
      minimizePane,
      spawnOrFocusTranscript,
      canvasId,
      workspaceHash,
      focusedPaneId,
      launch,
      launchStatus,
      launchSessionId,
    ],
  );

  return (
    <main className="canvas-route-shell" ref={surfaceRef}>
      <CanvasCommandBar
        focusedTitle={focusedTitle}
        launch={launch}
        onFocusPicker={() => focusPane(PICKER_PANE_ID)}
        onResetViewport={resetViewport}
      />
      {dropHint === null ? null : (
        <CanvasDropHint message={dropHint} onDismiss={() => setDropHint(null)} />
      )}
      <LayoutCanvas
        label={`Session canvas, ${layout.mode} mode`}
        layout={layout}
        onFocusPane={focusPane}
        onMovePane={movePane}
        onMovePaneEnd={onMovePaneEnd}
        onResizePane={resizePane}
        overlay={<PaneDock docked={docked} onClose={closeDockedPane} onRestore={restorePane} />}
        renderPane={renderPane}
        setViewport={setViewport}
        titleIdForPane={titleIdForPane}
      />
    </main>
  );
}

function titleIdForPane(paneId: string): string {
  return `canvas-pane-title-${paneId.replace(/[^a-zA-Z0-9_-]/g, "_")}`;
}
