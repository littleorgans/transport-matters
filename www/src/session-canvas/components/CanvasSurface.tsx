import { useCallback, useEffect, useMemo, useRef } from "react";
import { LayoutCanvas, type PaneId } from "../../engine";
import type { LaunchResolutionStatus } from "../api/launchResolution";
import { CanvasPaneDnd } from "../dnd/CanvasPaneDnd";
import { createSortablePaneAdapter } from "../dnd/SortablePane";
import { useCanvasDropTargets } from "../dnd/useCanvasDropTargets";
import { useReorderSettle } from "../dnd/useReorderSettle";
import { useCanvasStore } from "../model/canvasStore";
import { openPaneIds } from "../model/layoutPlanning";
import type { CanvasLaunchContext } from "../route";
import { bodyDragForRef, PICKER_PANE_ID, renderPaneContent } from "../viewers/registry";
import { CanvasCommandBar } from "./CanvasCommandBar";
import { CanvasDropHint } from "./CanvasDropHint";
import { CanvasDropTargetOverlay } from "./CanvasDropTargetOverlay";
import { PaneDock } from "./PaneDock";
import { PaneWindow } from "./PaneWindow";

export interface CanvasSurfaceProps {
  launch: CanvasLaunchContext;
  launchStatus: LaunchResolutionStatus;
  launchSessionId: string | null;
}

const paneBodyDrag = (paneId: PaneId): boolean => {
  const ref = useCanvasStore.getState().panes[paneId]?.contentRef;
  return ref ? bodyDragForRef(ref) : false;
};

// Module-stable adapter so the memoized PaneLayer keeps bailing on viewport
// renders. Scale reads non-reactively (consumed only mid-drag, zoom locked);
// the expanded hero stops lifting through a narrow reactive selector while
// staying a droppable delivery target.
const SortablePane = createSortablePaneAdapter({
  readWorldScale: () => useCanvasStore.getState().layout.viewport.scale,
  useLiftDisabled: (paneId) => useCanvasStore((state) => state.expandedPaneId === paneId),
});

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
  const dockPane = useCanvasStore((state) => state.dockPane);
  const commitReorder = useCanvasStore((state) => state.commitReorder);
  const spawnPane = useCanvasStore((state) => state.spawnPane);
  const resizePane = useCanvasStore((state) => state.resizePane);
  const restorePane = useCanvasStore((state) => state.restorePane);
  const restorePaneAtIndex = useCanvasStore((state) => state.restorePaneAtIndex);
  const setBounds = useCanvasStore((state) => state.setBounds);
  const setViewport = useCanvasStore((state) => state.setViewport);
  const resetViewport = useCanvasStore((state) => state.resetViewport);
  const spawnOrFocusTranscript = useCanvasStore((state) => state.spawnOrFocusTranscript);
  const surfaceRef = useRef<HTMLElement>(null);
  const focusedPaneId = layout.focusedPaneId;
  const focusedTitle = focusedPaneId ? (panes[focusedPaneId]?.title ?? null) : null;
  const { reorderActive, markReorderActive, finishReorder } = useReorderSettle();
  const dndDeps = useMemo(
    () => ({
      getLayout: () => useCanvasStore.getState().layout,
      contentRefFor: (paneId: string) => useCanvasStore.getState().panes[paneId]?.contentRef,
      titleFor: (paneId: string) => useCanvasStore.getState().panes[paneId]?.title ?? paneId,
      commitReorder,
      getSurfaceOrigin: () => {
        const rect = surfaceRef.current?.getBoundingClientRect();
        return rect ? { left: rect.left, top: rect.top } : { left: 0, top: 0 };
      },
      getExpandedPaneId: () => useCanvasStore.getState().expandedPaneId,
    }),
    [commitReorder],
  );
  // Open panes in committed order, minus the expanded hero (side column sorts,
  // the hero stays a delivery-only target). Memoized on the order/nodes refs so
  // viewport-only renders keep the same items array.
  const sortablePaneIds = useMemo(
    () => openPaneIds(layout).filter((paneId) => paneId !== expandedPaneId),
    [layout, expandedPaneId],
  );

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

  const { dropHint, dismissDropHint } = useCanvasDropTargets(surfaceRef, {
    getLayout: () => useCanvasStore.getState().layout,
    contentRefFor: (paneId) => useCanvasStore.getState().panes[paneId]?.contentRef,
    titleFor: (paneId) => useCanvasStore.getState().panes[paneId]?.title ?? paneId,
    spawnPane,
    dockPane,
    restorePaneAtIndex,
  });

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
      {dropHint === null ? null : <CanvasDropHint message={dropHint} onDismiss={dismissDropHint} />}
      <CanvasPaneDnd
        deps={dndDeps}
        onDragActiveChange={markReorderActive}
        onDragSettled={finishReorder}
        sortablePaneIds={sortablePaneIds}
      >
        <LayoutCanvas
          label={`Session canvas, ${layout.mode} mode`}
          layout={layout}
          onFocusPane={focusPane}
          onResizePane={resizePane}
          overlay={
            <>
              <PaneDock docked={docked} onClose={closeDockedPane} onRestore={restorePane} />
              <CanvasDropTargetOverlay layout={layout} />
            </>
          }
          paneBodyDrag={paneBodyDrag}
          paneDndAdapter={SortablePane}
          paneMotion={reorderActive}
          renderPane={renderPane}
          setViewport={setViewport}
          titleIdForPane={titleIdForPane}
          zoomLocked={reorderActive}
        />
      </CanvasPaneDnd>
    </main>
  );
}

function titleIdForPane(paneId: string): string {
  return `canvas-pane-title-${paneId.replace(/[^a-zA-Z0-9_-]/g, "_")}`;
}
