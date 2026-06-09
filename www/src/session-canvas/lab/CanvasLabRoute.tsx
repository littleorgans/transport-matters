import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LayoutCanvas } from "../../engine";
import { listLayouts } from "../../engine/layout";
import { CommandBarSections } from "../components/CommandBarSections";
import { PaneChrome } from "../components/PaneChrome";
import { RouteSwitcher } from "../components/RouteSwitcher";
import type { PaneContentRef, ViewerProps } from "../model/paneRecords";
import { renderPaneContent, titleForRef, viewerIdForRef } from "../viewers/registry";
import { ControlsPanel } from "./ControlsPanel";
import { framedPaneId, useCanvasLabStore } from "./canvasLabStore";
import { cliInstalled, useCapabilitiesStore } from "./capabilitiesStore";
import { useCapturedRunStore } from "./capturedRunStore";
import { DirectorPanel } from "./DirectorPanel";
import { LabCardPane } from "./viewers/LabCardPane";
import { LabRulerPane } from "./viewers/LabRulerPane";

const SEED_PANES = 4;

export function CanvasLabRoute() {
  const layout = useCanvasLabStore((state) => state.layout);
  const flying = useCanvasLabStore((state) => state.flying);
  const paneMotion = useCanvasLabStore((state) => state.paneMotion);
  const framedPane = useCanvasLabStore((state) => framedPaneId(state.framing));
  const expandedPane = useCanvasLabStore((state) => state.expandedPaneId);
  const activeStrategyId = useCanvasLabStore((state) => state.activeStrategyId);
  const fitToContent = useCanvasLabStore((state) => state.fitToContent);
  const contentRefs = useCanvasLabStore((state) => state.contentRefs);
  const addPane = useCanvasLabStore((state) => state.addPane);
  const addTerminal = useCanvasLabStore((state) => state.addTerminal);
  const addCapturedRun = useCanvasLabStore((state) => state.addCapturedRun);
  const restoreCapturedPane = useCanvasLabStore((state) => state.restoreCapturedPane);
  const organize = useCanvasLabStore((state) => state.organize);
  const hidePane = useCanvasLabStore((state) => state.hidePane);
  const closePane = useCanvasLabStore((state) => state.closePane);
  const focusPane = useCanvasLabStore((state) => state.focusPane);
  const expandPane = useCanvasLabStore((state) => state.expandPane);
  const framePane = useCanvasLabStore((state) => state.framePane);
  const updatePaneRect = useCanvasLabStore((state) => state.updatePaneRect);
  const setStrategy = useCanvasLabStore((state) => state.setStrategy);
  const setFitToContent = useCanvasLabStore((state) => state.setFitToContent);
  const setBounds = useCanvasLabStore((state) => state.setBounds);
  const setViewport = useCanvasLabStore((state) => state.setViewport);

  // Managed-CLI availability gates the captured-run spawn buttons: a CLI that is
  // not installed never offers a launch that would fail.
  const claudeInstalled = useCapabilitiesStore((state) => cliInstalled(state, "claude"));
  const codexInstalled = useCapabilitiesStore((state) => cliInstalled(state, "codex"));

  const stageRef = useRef<HTMLDivElement>(null);
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

  // Seed panes on first mount so expand mode starts with a dense right-column stress case.
  useEffect(() => {
    if (Object.keys(useCanvasLabStore.getState().layout.nodes).length > 0) return;
    for (let index = 0; index < SEED_PANES; index += 1) addPane();
  }, [addPane]);

  // Re-attach persisted runs on mount: a browser reload drops the in-memory lab store
  // but keeps each pane's run, so recreate a captured pane at every persisted key and
  // the pane re-attaches to its own run by id (output continues) instead of leaving the
  // headless run orphaned. restoreCapturedPane is idempotent across remounts.
  useEffect(() => {
    const { runs } = useCapturedRunStore.getState();
    for (const [paneId, record] of Object.entries(runs)) {
      restoreCapturedPane(paneId, record.provider);
    }
  }, [restoreCapturedPane]);

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
          // Captured panes can minimize ([-]): detach the run into the director for re-attach.
          // Other panes carry no run, so they only close.
          onMinimize={ref?.kind === "captured-run" ? () => hidePane(paneId) : undefined}
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
      hidePane,
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
    <main className="canvas-route-shell">
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
              </>
            }
            secondaryLabel="Layout"
          />
          <DirectorPanel />
        </div>
      )}
      <div className="canvas-lab-stage" ref={stageRef}>
        <LayoutCanvas
          framing={flying}
          label={`Canvas lab, ${activeStrategyId}`}
          layout={layout}
          onFocusPane={focusPane}
          onMovePane={updatePaneRect}
          onResizePane={updatePaneRect}
          paneMotion={paneMotion}
          renderPane={renderPane}
          setViewport={setViewport}
          titleIdForPane={titleIdForPane}
        />
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
