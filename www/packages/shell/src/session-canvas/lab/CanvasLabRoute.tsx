import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LayoutCanvas, type PaneId } from "../../engine";
import { CANVAS_LAYOUT_MARGIN, listLayouts } from "../../engine/layout";
import { useMeta } from "../../hooks/useMeta";
import { useThemeTokens } from "../../hooks/useThemeTokens";
import type { HarnessName } from "../../types";
import { AmbientBackdrop } from "../components/AmbientBackdrop";
import { CanvasDropHint } from "../components/CanvasDropHint";
import { CanvasDropTargetOverlay } from "../components/CanvasDropTargetOverlay";
import { CommandBarSections } from "../components/CommandBarSections";
import { PaneChrome } from "../components/PaneChrome";
import { PaneDock } from "../components/PaneDock";
import { RouteSwitcher } from "../components/RouteSwitcher";
import { SceneParamControls } from "../components/SceneParamControls";
import { ThemeCycleButton } from "../components/ThemeCycleButton";
import { CanvasPaneDnd } from "../dnd/CanvasPaneDnd";
import { createSortablePaneAdapter } from "../dnd/SortablePane";
import { useCanvasDropTargets } from "../dnd/useCanvasDropTargets";
import { useReorderSettle } from "../dnd/useReorderSettle";
import { openPaneIds } from "../model/layoutPlanning";
import type { PaneContentRef, ViewerProps } from "../model/paneRecords";
import { type CanvasLaunchContext, parseCanvasLaunchContext } from "../route";
import {
  bodyDragForRef,
  renderPaneContent,
  titleForRef,
  viewerIdForRef,
} from "../viewers/registry";
import { ControlsPanel, OscColorReplyToggle } from "./ControlsPanel";
import { framedPaneId, useCanvasLabStore } from "./canvasLabStore";
import { harnessInstalled, useCapabilitiesStore } from "./capabilitiesStore";
import "./canvas-lab.css";
import { LabCardPane } from "./viewers/LabCardPane";
import { LabRulerPane } from "./viewers/LabRulerPane";

const paneBodyDrag = (paneId: PaneId): boolean => {
  const ref = useCanvasLabStore.getState().contentRefs[paneId];
  return ref ? bodyDragForRef(ref) : false;
};

// Module-stable adapter so the memoized PaneLayer keeps bailing on viewport
// renders. Scale reads non-reactively (consumed only mid-drag, zoom locked);
// the expanded hero stops lifting through a narrow reactive selector while
// staying a droppable delivery target.
const SortablePane = createSortablePaneAdapter({
  readWorldScale: () => useCanvasLabStore.getState().layout.viewport.scale,
  useLiftDisabled: (paneId) => useCanvasLabStore((state) => state.expandedPaneId === paneId),
});

type CanvasLabStoreSnapshot = ReturnType<typeof useCanvasLabStore.getState>;

function useCanvasLabLaunch(): CanvasLaunchContext {
  const search = typeof window === "undefined" ? "" : window.location.search;
  const launch = useMemo(() => parseCanvasLaunchContext(search), [search]);
  const adoptDefaultWorktree = useCanvasLabStore((state) => state.adoptDefaultWorktree);
  const setDefaultWorktree = useCanvasLabStore((state) => state.setDefaultWorktree);
  const labSpaceId = useCanvasLabStore((state) => state.spaceId);
  const defaultWorktreeId = useCanvasLabStore((state) => state.defaultWorktreeId);
  const { meta } = useMeta();

  useEffect(() => {
    if (launch.worktreeId !== null) {
      setDefaultWorktree(launch.spaceId, launch.worktreeId);
      return;
    }
    if (!meta?.worktreeId) return;
    adoptDefaultWorktree(meta.spaceId, meta.worktreeId);
  }, [
    launch.spaceId,
    launch.worktreeId,
    meta?.spaceId,
    meta?.worktreeId,
    adoptDefaultWorktree,
    setDefaultWorktree,
  ]);

  return useMemo<CanvasLaunchContext>(
    () => ({
      ...launch,
      spaceId: launch.spaceId ?? labSpaceId,
      worktreeId: launch.worktreeId ?? defaultWorktreeId,
    }),
    [launch, labSpaceId, defaultWorktreeId],
  );
}

function useCanvasLabSpawnHandlers(
  addTerminal: CanvasLabStoreSnapshot["addTerminal"],
  addCapturedRun: CanvasLabStoreSnapshot["addCapturedRun"],
): {
  handleAddCapturedRun(provider: HarnessName): void;
  handleAddTerminal(): void;
} {
  const handleAddTerminal = useCallback(() => {
    try {
      addTerminal();
    } catch (error) {
      console.error("Failed to add terminal:", error);
    }
  }, [addTerminal]);

  const handleAddCapturedRun = useCallback(
    (provider: HarnessName) => {
      try {
        addCapturedRun(provider);
      } catch (error) {
        console.error("Failed to spawn captured run:", error);
      }
    },
    [addCapturedRun],
  );

  return { handleAddCapturedRun, handleAddTerminal };
}

interface CanvasLabPaneRendererOptions {
  closePane: CanvasLabStoreSnapshot["closePane"];
  contentRefs: CanvasLabStoreSnapshot["contentRefs"];
  expandedPane: string | null;
  expandPane: CanvasLabStoreSnapshot["expandPane"];
  focusPane: CanvasLabStoreSnapshot["focusPane"];
  focusedPaneId: string | null;
  framedPane: string | null;
  framePane: CanvasLabStoreSnapshot["framePane"];
  labLaunch: CanvasLaunchContext;
  minimizePane: CanvasLabStoreSnapshot["minimizePane"];
}

function useCanvasLabPaneRenderer({
  closePane,
  contentRefs,
  expandedPane,
  expandPane,
  focusPane,
  focusedPaneId,
  framedPane,
  framePane,
  labLaunch,
  minimizePane,
}: CanvasLabPaneRendererOptions): (paneId: string) => React.ReactNode {
  return useCallback(
    (paneId: string) => {
      // Real content dispatches through the shared viewer registry, so a new viewer is a
      // registry entry, not a branch here. The lab stubs stay local because they prove layouts.
      const ref = contentRefs[paneId];
      const demoIsRuler = paneIndexOf(paneId) % 2 === 1;
      return (
        <PaneChrome
          badge={ref ? ref.kind : demoIsRuler ? "ruler" : "card"}
          compact
          expanded={expandedPane === paneId}
          focused={focusedPaneId === paneId}
          onClose={() => closePane(paneId)}
          onExpand={() => expandPane(paneId)}
          onFrame={() => framePane(paneId)}
          onHeaderDoubleClick={(event) => (event.shiftKey ? expandPane(paneId) : framePane(paneId))}
          onMinimize={() => minimizePane(paneId)}
          state={framedPane === paneId ? "framed" : "default"}
          title={ref ? titleForRef(ref) : paneId}
          titleId={titleIdForPane(paneId)}
        >
          {ref ? (
            renderPaneContent(
              labContentProps(paneId, ref, focusedPaneId, closePane, focusPane, labLaunch),
            )
          ) : demoIsRuler ? (
            <LabRulerPane paneId={paneId} />
          ) : (
            <LabCardPane paneId={paneId} />
          )}
        </PaneChrome>
      );
    },
    [
      closePane,
      contentRefs,
      expandedPane,
      expandPane,
      focusPane,
      focusedPaneId,
      framedPane,
      framePane,
      labLaunch,
      minimizePane,
    ],
  );
}

interface CanvasLabCommandBarProps {
  activeStrategyId: string;
  claudeInstalled: boolean;
  codexInstalled: boolean;
  fitToContent: boolean;
  onAddCapturedRun(provider: HarnessName): void;
  onAddPane(): void;
  onAddTerminal(): void;
  onOrganize(): void;
  onSetFitToContent(on: boolean): void;
  onSetStrategy(strategyId: string): void;
  onSetTextShadow(on: boolean): void;
  paneCount: number;
  textShadow: boolean;
}

function CanvasLabCommandBar({
  activeStrategyId,
  claudeInstalled,
  codexInstalled,
  fitToContent,
  onAddCapturedRun,
  onAddPane,
  onAddTerminal,
  onOrganize,
  onSetFitToContent,
  onSetStrategy,
  onSetTextShadow,
  paneCount,
  textShadow,
}: CanvasLabCommandBarProps) {
  const strategies = useMemo(() => listLayouts(), []);

  return (
    <div
      aria-label="Canvas lab controls"
      className="canvas-command-bar canvas-command-bar--lab"
      role="toolbar"
    >
      <div className="canvas-command-bar__identity">
        <span>Canvas lab</span>
        <span>{paneCount} panes</span>
      </div>
      <CommandBarSections
        primary={
          <>
            <RouteSwitcher />
            <button className="canvas-button" onClick={onAddPane} type="button">
              Add pane
            </button>
            <button className="canvas-button" onClick={onOrganize} type="button">
              Organize
            </button>
            <button className="canvas-button" onClick={onAddTerminal} type="button">
              Add terminal
            </button>
            {claudeInstalled ? (
              <button
                className="canvas-button"
                onClick={() => onAddCapturedRun("claude")}
                type="button"
              >
                Spawn Claude
              </button>
            ) : null}
            {codexInstalled ? (
              <button
                className="canvas-button"
                onClick={() => onAddCapturedRun("codex")}
                type="button"
              >
                Spawn Codex
              </button>
            ) : null}
            <ThemeCycleButton />
          </>
        }
        secondary={
          <>
            <label className="canvas-lab-toggle">
              <input
                checked={fitToContent}
                onChange={(event) => onSetFitToContent(event.target.checked)}
                type="checkbox"
              />
              Fit to content
            </label>
            <label className="canvas-lab-toggle">
              <input
                checked={textShadow}
                onChange={(event) => onSetTextShadow(event.target.checked)}
                type="checkbox"
              />
              Text shadow
            </label>
            <OscColorReplyToggle />
            <select
              aria-label="Layout strategy"
              onChange={(event) => onSetStrategy(event.target.value)}
              value={activeStrategyId}
            >
              {strategies.map((strategy) => (
                <option key={strategy.id} value={strategy.id}>
                  {strategy.label}
                </option>
              ))}
            </select>
            <ControlsPanel />
            <SceneParamControls />
          </>
        }
        secondaryLabel="Layout"
      />
    </div>
  );
}

function useCanvasLabChromeHidden(): boolean {
  const [chromeHidden, setChromeHidden] = useState(false);

  // Tab toggles the command bar so the whole viewport reads as canvas. preventDefault
  // stops focus traversal; this is an experimental cockpit shortcut.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Tab" || event.metaKey || event.ctrlKey || event.altKey) return;
      event.preventDefault();
      setChromeHidden((hidden) => !hidden);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return chromeHidden;
}

function useCanvasLabDnd(
  stageRef: React.RefObject<HTMLDivElement | null>,
  commitReorder: CanvasLabStoreSnapshot["commitReorder"],
  spawnPane: CanvasLabStoreSnapshot["spawnPane"],
  dockPane: CanvasLabStoreSnapshot["dockPane"],
  restorePaneAtIndex: CanvasLabStoreSnapshot["restorePaneAtIndex"],
) {
  const dndDeps = useMemo(
    () => ({
      getLayout: () => useCanvasLabStore.getState().layout,
      contentRefFor: (paneId: string) => useCanvasLabStore.getState().contentRefs[paneId],
      titleFor: (paneId: string) => {
        const ref = useCanvasLabStore.getState().contentRefs[paneId];
        return ref ? titleForRef(ref) : paneId;
      },
      commitReorder,
      getSurfaceOrigin: () => {
        const rect = stageRef.current?.getBoundingClientRect();
        return rect ? { left: rect.left, top: rect.top } : { left: 0, top: 0 };
      },
      getExpandedPaneId: () => useCanvasLabStore.getState().expandedPaneId,
    }),
    [commitReorder, stageRef],
  );
  const { dropHint, dismissDropHint } = useCanvasDropTargets(stageRef, {
    getLayout: () => useCanvasLabStore.getState().layout,
    contentRefFor: (paneId) => useCanvasLabStore.getState().contentRefs[paneId],
    titleFor: (paneId) => {
      const ref = useCanvasLabStore.getState().contentRefs[paneId];
      return ref ? titleForRef(ref) : paneId;
    },
    spawnPane,
    dockPane,
    restorePaneAtIndex,
  });

  return { dismissDropHint, dndDeps, dropHint };
}

function useCanvasLabResize(
  stageRef: React.RefObject<HTMLDivElement | null>,
  setBounds: CanvasLabStoreSnapshot["setBounds"],
): void {
  // Plan in world units that match the visible stage; re-plan on resize.
  useEffect(() => {
    const element = stageRef.current;
    if (!element) return;
    const measure = () => setBounds({ width: element.clientWidth, height: element.clientHeight });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [setBounds, stageRef]);
}

export function CanvasLabRoute() {
  useThemeTokens();
  const layout = useCanvasLabStore((state) => state.layout);
  const flying = useCanvasLabStore((state) => state.flying);
  const paneMotion = useCanvasLabStore((state) => state.paneMotion);
  const framedPane = useCanvasLabStore((state) => framedPaneId(state.framing));
  const expandedPane = useCanvasLabStore((state) => state.expandedPaneId);
  const activeStrategyId = useCanvasLabStore((state) => state.activeStrategyId);
  const fitToContent = useCanvasLabStore((state) => state.fitToContent);
  const textShadow = useCanvasLabStore((state) => state.textShadow);
  const contentRefs = useCanvasLabStore((state) => state.contentRefs);
  const docked = useCanvasLabStore((state) => state.docked);
  const addPane = useCanvasLabStore((state) => state.addPane);
  const addTerminal = useCanvasLabStore((state) => state.addTerminal);
  const addCapturedRun = useCanvasLabStore((state) => state.addCapturedRun);
  const spawnPane = useCanvasLabStore((state) => state.spawnPane);
  const dockPane = useCanvasLabStore((state) => state.dockPane);
  const organize = useCanvasLabStore((state) => state.organize);
  const minimizePane = useCanvasLabStore((state) => state.minimizePane);
  const closePane = useCanvasLabStore((state) => state.closePane);
  const restorePane = useCanvasLabStore((state) => state.restorePane);
  const restorePaneAtIndex = useCanvasLabStore((state) => state.restorePaneAtIndex);
  const closeDockedPane = useCanvasLabStore((state) => state.closeDockedPane);
  const focusPane = useCanvasLabStore((state) => state.focusPane);
  const expandPane = useCanvasLabStore((state) => state.expandPane);
  const framePane = useCanvasLabStore((state) => state.framePane);
  const updatePaneRect = useCanvasLabStore((state) => state.updatePaneRect);
  const commitReorder = useCanvasLabStore((state) => state.commitReorder);
  const setStrategy = useCanvasLabStore((state) => state.setStrategy);
  const setFitToContent = useCanvasLabStore((state) => state.setFitToContent);
  const setTextShadow = useCanvasLabStore((state) => state.setTextShadow);
  const setBounds = useCanvasLabStore((state) => state.setBounds);
  const setViewport = useCanvasLabStore((state) => state.setViewport);

  // Managed harness availability gates the captured-run spawn buttons: a harness that is
  // not installed never offers a launch that would fail.
  const claudeInstalled = useCapabilitiesStore((state) => harnessInstalled(state, "claude"));
  const codexInstalled = useCapabilitiesStore((state) => harnessInstalled(state, "codex"));
  const labLaunch = useCanvasLabLaunch();
  const { handleAddCapturedRun, handleAddTerminal } = useCanvasLabSpawnHandlers(
    addTerminal,
    addCapturedRun,
  );

  const stageRef = useRef<HTMLDivElement>(null);
  const { reorderActive, markReorderActive, finishReorder } = useReorderSettle();
  const { dismissDropHint, dndDeps, dropHint } = useCanvasLabDnd(
    stageRef,
    commitReorder,
    spawnPane,
    dockPane,
    restorePaneAtIndex,
  );
  const sortablePaneIds = useMemo(
    () => openPaneIds(layout).filter((paneId) => paneId !== expandedPane),
    [layout, expandedPane],
  );
  const chromeHidden = useCanvasLabChromeHidden();

  // Reload restore is owned by the lab store's own persistence: the persisted record set rehydrates the
  // canvas (open panes) and the dock (every kind) synchronously at store creation, through the one
  // seedPaneFromRecord path that spawn uses. A captured pane re-attaches to its own run by id when its
  // viewer mounts (capturedRunStore keeps the runId), so no mount-time reconcile is needed here.

  // Probe managed harness availability once so the Spawn buttons reflect what's installed.
  useEffect(() => {
    useCapabilitiesStore.getState().ensureLoaded();
  }, []);

  useCanvasLabResize(stageRef, setBounds);

  const paneCount = Object.keys(layout.nodes).length;

  const focusedPaneId = layout.focusedPaneId;
  const renderPane = useCanvasLabPaneRenderer({
    closePane,
    contentRefs,
    expandedPane,
    expandPane,
    focusPane,
    focusedPaneId,
    framedPane,
    framePane,
    labLaunch,
    minimizePane,
  });

  return (
    <main
      className="canvas-route-shell"
      // CSS hook for the glyph-halo styles (terminal-pane.css); absent when off.
      data-text-shadow={textShadow ? "" : undefined}
      // Single source for the pane-grid top margin (world units) AND the dock-band height (screen
      // px): both read --canvas-layout-margin, set once here from the layout const.
      style={{ "--canvas-layout-margin": `${CANVAS_LAYOUT_MARGIN}px` } as React.CSSProperties}
    >
      <AmbientBackdrop />
      {chromeHidden ? null : (
        <CanvasLabCommandBar
          activeStrategyId={activeStrategyId}
          claudeInstalled={claudeInstalled}
          codexInstalled={codexInstalled}
          fitToContent={fitToContent}
          onAddCapturedRun={handleAddCapturedRun}
          onAddPane={addPane}
          onAddTerminal={handleAddTerminal}
          onOrganize={organize}
          onSetFitToContent={setFitToContent}
          onSetStrategy={setStrategy}
          onSetTextShadow={setTextShadow}
          paneCount={paneCount}
          textShadow={textShadow}
        />
      )}
      <div className="canvas-lab-stage" ref={stageRef}>
        {dropHint === null ? null : (
          <CanvasDropHint message={dropHint} onDismiss={dismissDropHint} />
        )}
        <CanvasPaneDnd
          deps={dndDeps}
          onDragActiveChange={markReorderActive}
          onDragSettled={finishReorder}
          sortablePaneIds={sortablePaneIds}
        >
          <LayoutCanvas
            framing={flying}
            label={`Canvas lab, ${activeStrategyId}`}
            layout={layout}
            onFocusPane={focusPane}
            onResizePane={updatePaneRect}
            // Canvas-resident dock: top band, screen-space, survives the TAB hide of the command bar.
            overlay={
              <>
                <PaneDock docked={docked} onClose={closeDockedPane} onRestore={restorePane} />
                <CanvasDropTargetOverlay layout={layout} />
              </>
            }
            paneBodyDrag={paneBodyDrag}
            paneDndAdapter={SortablePane}
            paneMotion={paneMotion || reorderActive}
            renderPane={renderPane}
            setViewport={setViewport}
            titleIdForPane={titleIdForPane}
            zoomLocked={reorderActive}
          />
        </CanvasPaneDnd>
      </div>
    </main>
  );
}

function titleIdForPane(paneId: string): string {
  return `canvas-lab-title-${paneId.replace(/[^a-zA-Z0-9_-]/g, "_")}`;
}

function paneIndexOf(paneId: string): number {
  const parsed = Number.parseInt(paneId.replace(/^lab-/, ""), 10);
  return Number.isFinite(parsed) ? parsed : 0;
}

const noop = (): void => {};

// The lab has no session context, so it synthesizes the minimal ViewerProps the registry needs.
// Lab content viewers (terminal, future fixtures) are self-contained and ignore the canvas/actions
// context; the fields exist only to satisfy the shared contract.
function labContentProps(
  paneId: string,
  ref: PaneContentRef,
  focusedPaneId: string | null,
  closePane: (paneId: string) => void,
  focusPane: (paneId: string) => void,
  launch: CanvasLaunchContext,
): ViewerProps {
  return {
    pane: {
      paneId,
      viewerId: viewerIdForRef(ref),
      title: titleForRef(ref),
      contentRef: ref,
      chromeState: "default",
      createdAt: "",
      lastFocusedAt: null,
    },
    canvas: {
      id: "canvas-lab",
      owner: "local",
      workspaceHash: launch.workspaceHash,
      focusedPaneId,
      launch,
      launchStatus: "unavailable",
      launchSessionId: null,
    },
    actions: { closePane, focusPane, spawnOrFocusTranscript: noop },
  };
}
