import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LayoutCanvas, type PaneId } from "../../engine";
import { CANVAS_LAYOUT_MARGIN, listLayouts } from "../../engine/layout";
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
import {
  bodyDragForRef,
  renderPaneContent,
  titleForRef,
  viewerIdForRef,
} from "../viewers/registry";
import { ControlsPanel } from "./ControlsPanel";
import { framedPaneId, useCanvasLabStore } from "./canvasLabStore";
import { cliInstalled, useCapabilitiesStore } from "./capabilitiesStore";
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

export function CanvasLabRoute() {
  const layout = useCanvasLabStore((state) => state.layout);
  const flying = useCanvasLabStore((state) => state.flying);
  const paneMotion = useCanvasLabStore((state) => state.paneMotion);
  const framedPane = useCanvasLabStore((state) => framedPaneId(state.framing));
  const expandedPane = useCanvasLabStore((state) => state.expandedPaneId);
  const activeStrategyId = useCanvasLabStore((state) => state.activeStrategyId);
  const fitToContent = useCanvasLabStore((state) => state.fitToContent);
  const textShadow = useCanvasLabStore((state) => state.textShadow);
  const oscColorReplies = useCanvasLabStore((state) => state.oscColorReplies);
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
  const setOscColorReplies = useCanvasLabStore((state) => state.setOscColorReplies);
  const setBounds = useCanvasLabStore((state) => state.setBounds);
  const setViewport = useCanvasLabStore((state) => state.setViewport);

  // Managed-CLI availability gates the captured-run spawn buttons: a CLI that is
  // not installed never offers a launch that would fail.
  const claudeInstalled = useCapabilitiesStore((state) => cliInstalled(state, "claude"));
  const codexInstalled = useCapabilitiesStore((state) => cliInstalled(state, "codex"));

  const stageRef = useRef<HTMLDivElement>(null);
  const { reorderActive, markReorderActive, finishReorder } = useReorderSettle();
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
    [commitReorder],
  );
  const sortablePaneIds = useMemo(
    () => openPaneIds(layout).filter((paneId) => paneId !== expandedPane),
    [layout, expandedPane],
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
  const strategies = useMemo(() => listLayouts(), []);
  const [chromeHidden, setChromeHidden] = useState(false);

  // Tab toggles the command bar so the whole viewport reads as canvas (the bar floats over the top
  // pane row). preventDefault stops focus traversal; this is an experimental cockpit shortcut.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Tab" || event.metaKey || event.ctrlKey || event.altKey) return;
      event.preventDefault();
      setChromeHidden((hidden) => !hidden);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  // Reload restore is owned by the lab store's own persistence: the persisted record set rehydrates the
  // canvas (open panes) and the dock (every kind) synchronously at store creation, through the one
  // seedPaneFromRecord path that spawn uses. A captured pane re-attaches to its own run by id when its
  // viewer mounts (capturedRunStore keeps the runId), so no mount-time reconcile is needed here.

  // Probe managed-CLI availability once so the Spawn buttons reflect what's installed.
  useEffect(() => {
    useCapabilitiesStore.getState().ensureLoaded();
  }, []);

  // Plan in world units that match the visible stage; re-plan on resize.
  useEffect(() => {
    const element = stageRef.current;
    if (!element) return;
    const measure = () => setBounds({ width: element.clientWidth, height: element.clientHeight });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [setBounds]);

  const paneCount = Object.keys(layout.nodes).length;

  // Stable across viewport-only renders so the memoized PaneLayer skips the pane subtree on pan/zoom.
  // Re-created only when focus, framing, or the close/frame actions change (the things it reads).
  const focusedPaneId = layout.focusedPaneId;
  const renderPane = useCallback(
    (paneId: string) => {
      // Real content (terminal, future fixtures) dispatches through the shared viewer registry, so a
      // new viewer is a registry entry, not a branch here. The lab's card/ruler stubs read the lab
      // store directly (they prove layouts, not content), so they stay lab-local.
      const ref = contentRefs[paneId];
      const demoIsRuler = paneIndexOf(paneId) % 2 === 1;
      return (
        <PaneChrome
          badge={ref ? ref.kind : demoIsRuler ? "ruler" : "card"}
          compact
          expanded={expandedPane === paneId}
          focused={focusedPaneId === paneId}
          onClose={() => closePane(paneId)}
          // Every pane can minimize ([-]) into the dock; only the side effect differs by kind (the
          // captured-run policy keeps its run alive, plain panes just park their ref). Universal
          // chrome, no per-kind gate.
          onMinimize={() => minimizePane(paneId)}
          onExpand={() => expandPane(paneId)}
          onFrame={() => framePane(paneId)}
          onHeaderDoubleClick={(event) => (event.shiftKey ? expandPane(paneId) : framePane(paneId))}
          state={framedPane === paneId ? "framed" : "default"}
          // Content panes show their viewer title (e.g. "Claude", "Codex", "Terminal"); demo
          // card/ruler stubs keep the raw pane id. The compact header keeps it to one line.
          title={ref ? titleForRef(ref) : paneId}
          titleId={titleIdForPane(paneId)}
        >
          {ref ? (
            renderPaneContent(labContentProps(paneId, ref, focusedPaneId, closePane, focusPane))
          ) : demoIsRuler ? (
            <LabRulerPane paneId={paneId} />
          ) : (
            <LabCardPane paneId={paneId} />
          )}
        </PaneChrome>
      );
    },
    [
      contentRefs,
      minimizePane,
      closePane,
      focusPane,
      expandPane,
      framePane,
      framedPane,
      expandedPane,
      focusedPaneId,
    ],
  );

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
                <button className="canvas-button" onClick={addPane} type="button">
                  Add pane
                </button>
                <button className="canvas-button" onClick={organize} type="button">
                  Organize
                </button>
                <button className="canvas-button" onClick={addTerminal} type="button">
                  Add terminal
                </button>
                {claudeInstalled ? (
                  <button
                    className="canvas-button"
                    onClick={() => addCapturedRun("claude")}
                    type="button"
                  >
                    Spawn Claude
                  </button>
                ) : null}
                {codexInstalled ? (
                  <button
                    className="canvas-button"
                    onClick={() => addCapturedRun("codex")}
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
                    onChange={(event) => setFitToContent(event.target.checked)}
                    type="checkbox"
                  />
                  Fit to content
                </label>
                <label className="canvas-lab-toggle">
                  <input
                    checked={textShadow}
                    onChange={(event) => setTextShadow(event.target.checked)}
                    type="checkbox"
                  />
                  Text shadow
                </label>
                <label className="canvas-lab-toggle">
                  <input
                    checked={oscColorReplies}
                    onChange={(event) => setOscColorReplies(event.target.checked)}
                    type="checkbox"
                  />
                  CLI color replies
                </label>
                <select
                  aria-label="Layout strategy"
                  onChange={(event) => setStrategy(event.target.value)}
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
      workspaceHash: null,
      focusedPaneId,
      launch: { owner: "local", workspaceHash: null, cli: null, runId: null },
      launchStatus: "unavailable",
      launchSessionId: null,
    },
    actions: { closePane, focusPane, spawnOrFocusTranscript: noop },
  };
}
