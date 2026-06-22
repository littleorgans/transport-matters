import { useCallback, useEffect, useMemo, useRef } from "react";
import { LayoutCanvas, type PaneId } from "../../engine";
import { shouldPanNotDrag } from "../../keybindings/gestures";
import { useKeymapStore } from "../../stores/keymapStore";
import { useThemeStore } from "../../stores/themeStore";
import type { LaunchResolutionStatus } from "../api/launchResolution";
import { CanvasPaneDnd } from "../dnd/CanvasPaneDnd";
import { createSortablePaneAdapter } from "../dnd/SortablePane";
import { useCanvasDropTargets } from "../dnd/useCanvasDropTargets";
import { useReorderSettle } from "../dnd/useReorderSettle";
import { CommandCenter } from "../launcher/CommandCenter";
import type { LauncherCommand } from "../launcher/commandModel";
import { useCanvasStore } from "../model/canvasStore";
import { useCapturedRunStore } from "../model/capturedRunStore";
import { openPaneIds } from "../model/layoutPlanning";
import { type CanvasLaunchContext, parseCanvasLaunchContext, worktreeSwitchUrl } from "../route";
import { bodyDragForRef, PICKER_PANE_ID, renderPaneContent } from "../viewers/registry";
import { AmbientBackdrop } from "./AmbientBackdrop";
import { CanvasDropHint } from "./CanvasDropHint";
import { CanvasDropTargetOverlay } from "./CanvasDropTargetOverlay";
import { PaneDock } from "./PaneDock";
import { PaneWindow } from "./PaneWindow";
import { navigateToRoute } from "./RouteSwitcher";

export interface CanvasSurfaceProps {
  capturedRunsReady?: boolean;
  launch: CanvasLaunchContext;
  launchStatus: LaunchResolutionStatus;
  launchSessionId: string | null;
}

const paneBodyDrag = (paneId: PaneId): boolean => {
  const ref = useCanvasStore.getState().panes[paneId]?.contentRef;
  return ref ? bodyDragForRef(ref) : false;
};

type CanvasStoreSnapshot = ReturnType<typeof useCanvasStore.getState>;
type CapturedRunStoreSnapshot = ReturnType<typeof useCapturedRunStore.getState>;
type KeymapStoreSnapshot = ReturnType<typeof useKeymapStore.getState>;
type ThemeStoreSnapshot = ReturnType<typeof useThemeStore.getState>;

interface CanvasCommandHandlerOptions {
  addCapturedRun: CanvasStoreSnapshot["addCapturedRun"];
  cycleTheme: ThemeStoreSnapshot["cycleTheme"];
  focusPane: CanvasStoreSnapshot["focusPane"];
  resetViewport: CanvasStoreSnapshot["resetViewport"];
  setCanvasGestureModifier: KeymapStoreSnapshot["setCanvasGestureModifier"];
  toggleBypassPermissions: CapturedRunStoreSnapshot["toggleBypassPermissions"];
}

interface CanvasPaneRendererOptions {
  canvasId: CanvasStoreSnapshot["canvasId"];
  closePane: CanvasStoreSnapshot["closePane"];
  expandedPaneId: CanvasStoreSnapshot["expandedPaneId"];
  expandPane: CanvasStoreSnapshot["expandPane"];
  focusPane: CanvasStoreSnapshot["focusPane"];
  focusedPaneId: CanvasStoreSnapshot["layout"]["focusedPaneId"];
  framedPaneId: CanvasStoreSnapshot["framing"]["paneId"];
  framePane: CanvasStoreSnapshot["framePane"];
  capturedRunsReady: boolean;
  launch: CanvasLaunchContext;
  launchSessionId: string | null;
  launchStatus: LaunchResolutionStatus;
  minimizePane: CanvasStoreSnapshot["minimizePane"];
  panes: CanvasStoreSnapshot["panes"];
  spawnOrFocusTranscript: CanvasStoreSnapshot["spawnOrFocusTranscript"];
  workspaceHash: CanvasStoreSnapshot["workspaceHash"];
}

// Module-stable adapter so the memoized PaneLayer keeps bailing on viewport
// renders. Scale reads non-reactively (consumed only mid-drag, zoom locked);
// the expanded hero stops lifting through a narrow reactive selector while
// staying a droppable delivery target.
const SortablePane = createSortablePaneAdapter({
  readWorldScale: () => useCanvasStore.getState().layout.viewport.scale,
  useLiftDisabled: (paneId) => useCanvasStore((state) => state.expandedPaneId === paneId),
});

function useCanvasCommandHandler({
  addCapturedRun,
  cycleTheme,
  focusPane,
  resetViewport,
  setCanvasGestureModifier,
  toggleBypassPermissions,
}: CanvasCommandHandlerOptions): (command: LauncherCommand) => void {
  return useCallback(
    (command: LauncherCommand) => {
      switch (command.kind) {
        case "spawn":
          try {
            // addCapturedRun throws on a canvas with no rooted worktree
            // (plain/legacy /canvas, defaultWorktreeId === null): a captured run
            // can't resolve a cwd. Surface it as a non-fatal error instead of
            // letting it bubble out of the event handler and crash the surface.
            addCapturedRun(command.harness, command.runtimeTemplate);
          } catch (error) {
            console.error("Failed to spawn captured run:", error);
          }
          return;
        case "reset-view":
          resetViewport();
          return;
        case "focus-picker":
          focusPane(PICKER_PANE_ID);
          return;
        case "goto":
          navigateToRoute(command.path);
          return;
        case "cycle-theme":
          cycleTheme();
          return;
        case "toggle-bypass-permissions":
          toggleBypassPermissions();
          return;
        case "set-canvas-gesture-modifier":
          setCanvasGestureModifier(command.modifier);
          return;
        case "select-worktree": {
          // Set the query EXACTLY once via replaceState (passing a query-bearing path
          // to navigateToRoute would re-append window.location.search → a double-"?"
          // URL that corrupts worktree_id on reload), then re-root the canvas in place.
          window.history.replaceState(
            {},
            "",
            worktreeSwitchUrl(
              window.location.pathname,
              window.location.search,
              command.spaceId,
              command.worktreeId,
            ),
          );
          useCanvasStore
            .getState()
            .initializeCanvas(parseCanvasLaunchContext(window.location.search));
          return;
        }
      }
    },
    [
      addCapturedRun,
      resetViewport,
      focusPane,
      cycleTheme,
      setCanvasGestureModifier,
      toggleBypassPermissions,
    ],
  );
}

function useCanvasPaneRenderer({
  canvasId,
  closePane,
  expandedPaneId,
  expandPane,
  focusPane,
  focusedPaneId,
  framedPaneId,
  framePane,
  capturedRunsReady,
  launch,
  launchSessionId,
  launchStatus,
  minimizePane,
  panes,
  spawnOrFocusTranscript,
  workspaceHash,
}: CanvasPaneRendererOptions): (paneId: string) => React.ReactNode {
  const onHeaderActivate = useCallback(
    (paneId: PaneId, modifierEngaged: boolean) => {
      if (modifierEngaged) expandPane(paneId);
      else framePane(paneId);
    },
    [expandPane, framePane],
  );

  return useCallback(
    (paneId: string) => {
      const pane = panes[paneId];
      if (!pane) return null;
      const titleId = titleIdForPane(paneId);
      const content =
        pane.contentRef.kind === "captured-run" && !capturedRunsReady ? (
          <div
            aria-busy="true"
            className="canvas-transcript canvas-transcript--center"
            data-testid="captured-run-reconciliation-placeholder"
          >
            <p>Checking captured run state…</p>
          </div>
        ) : (
          renderPaneContent({
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
          })
        );
      return (
        <PaneWindow
          expanded={expandedPaneId === paneId}
          framed={framedPaneId === paneId}
          focused={focusedPaneId === paneId}
          onClose={() => closePane(paneId)}
          onExpand={() => expandPane(paneId)}
          onFrame={() => framePane(paneId)}
          onHeaderDoubleClick={(event) => onHeaderActivate(paneId, shouldPanNotDrag(event))}
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
      capturedRunsReady,
      focusPane,
      minimizePane,
      onHeaderActivate,
      spawnOrFocusTranscript,
      canvasId,
      workspaceHash,
      focusedPaneId,
      launch,
      launchStatus,
      launchSessionId,
    ],
  );
}

export function CanvasSurface({
  capturedRunsReady = true,
  launch,
  launchStatus,
  launchSessionId,
}: CanvasSurfaceProps) {
  const layout = useCanvasStore((state) => state.layout);
  const panes = useCanvasStore((state) => state.panes);
  const canvasId = useCanvasStore((state) => state.canvasId);
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
  const addCapturedRun = useCanvasStore((state) => state.addCapturedRun);
  const themeName = useThemeStore((state) => state.theme?.name ?? "NONE");
  const cycleTheme = useThemeStore((state) => state.cycleTheme);
  const canvasGestureModifier = useKeymapStore((state) => state.canvasGestureModifier);
  const setCanvasGestureModifier = useKeymapStore((state) => state.setCanvasGestureModifier);
  const bypassPermissions = useCapturedRunStore((state) => state.bypassPermissions);
  const toggleBypassPermissions = useCapturedRunStore((state) => state.toggleBypassPermissions);
  const surfaceRef = useRef<HTMLElement>(null);
  const focusedPaneId = layout.focusedPaneId;
  const { reorderActive, markReorderActive, finishReorder } = useReorderSettle();

  // The command center re-homes the deleted command bar's functions: every leaf
  // entry routes to the SAME existing handler, so zero-chrome regresses nothing.
  const handleCommand = useCanvasCommandHandler({
    addCapturedRun,
    cycleTheme,
    focusPane,
    resetViewport,
    setCanvasGestureModifier,
    toggleBypassPermissions,
  });
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
  const renderPane = useCanvasPaneRenderer({
    canvasId,
    closePane,
    expandedPaneId,
    expandPane,
    focusPane,
    focusedPaneId,
    framedPaneId,
    framePane,
    capturedRunsReady,
    launch,
    launchSessionId,
    launchStatus,
    minimizePane,
    panes,
    spawnOrFocusTranscript,
    workspaceHash,
  });

  return (
    <main className="canvas-route-shell" ref={surfaceRef}>
      <AmbientBackdrop />
      <CommandCenter
        bypassPermissions={bypassPermissions}
        canvasGestureModifier={canvasGestureModifier}
        onCommand={handleCommand}
        themeName={themeName}
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
