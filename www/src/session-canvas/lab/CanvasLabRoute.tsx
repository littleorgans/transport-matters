import { useEffect, useMemo, useRef } from "react";
import { LayoutCanvas } from "../../engine";
import { listLayouts } from "../../engine/layout";
import { PaneChrome } from "../components/PaneChrome";
import { ControlsPanel } from "./ControlsPanel";
import { useCanvasLabStore } from "./canvasLabStore";
import { LabCardPane } from "./viewers/LabCardPane";
import { LabRulerPane } from "./viewers/LabRulerPane";

const SEED_PANES = 3;

export function CanvasLabRoute() {
  const layout = useCanvasLabStore((state) => state.layout);
  const flying = useCanvasLabStore((state) => state.flying);
  const framedPaneId = useCanvasLabStore((state) => state.framing.framedPaneId);
  const activeStrategyId = useCanvasLabStore((state) => state.activeStrategyId);
  const fitToContent = useCanvasLabStore((state) => state.fitToContent);
  const addPane = useCanvasLabStore((state) => state.addPane);
  const organize = useCanvasLabStore((state) => state.organize);
  const closePane = useCanvasLabStore((state) => state.closePane);
  const focusPane = useCanvasLabStore((state) => state.focusPane);
  const framePane = useCanvasLabStore((state) => state.framePane);
  const updatePaneRect = useCanvasLabStore((state) => state.updatePaneRect);
  const setStrategy = useCanvasLabStore((state) => state.setStrategy);
  const setFitToContent = useCanvasLabStore((state) => state.setFitToContent);
  const setBounds = useCanvasLabStore((state) => state.setBounds);
  const setViewport = useCanvasLabStore((state) => state.setViewport);

  const stageRef = useRef<HTMLDivElement>(null);
  const strategies = useMemo(() => listLayouts(), []);

  // Seed a few panes on first mount so the lab is not empty (count guard survives StrictMode).
  useEffect(() => {
    if (Object.keys(useCanvasLabStore.getState().layout.nodes).length > 0) return;
    for (let index = 0; index < SEED_PANES; index += 1) addPane();
  }, [addPane]);

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

  return (
    <main className="canvas-route-shell">
      <div
        aria-label="Canvas lab controls"
        className="canvas-command-bar canvas-command-bar--lab"
        role="toolbar"
      >
        <div className="canvas-command-bar__identity">
          <span>Canvas lab</span>
          <span>{paneCount} panes</span>
        </div>
        <div className="canvas-command-bar__buttons">
          <button className="canvas-button" onClick={addPane} type="button">
            Add pane
          </button>
          <button className="canvas-button" onClick={organize} type="button">
            Organize
          </button>
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
        </div>
        <ControlsPanel />
      </div>
      <div className="canvas-lab-stage" ref={stageRef}>
        <LayoutCanvas
          framing={flying}
          label={`Canvas lab, ${activeStrategyId}`}
          layout={layout}
          onFocusPane={focusPane}
          onMovePane={updatePaneRect}
          onResizePane={updatePaneRect}
          renderPane={(paneId) => {
            const isRuler = paneIndexOf(paneId) % 2 === 1;
            return (
              <PaneChrome
                badge={isRuler ? "ruler" : "card"}
                focused={layout.focusedPaneId === paneId}
                onClose={() => closePane(paneId)}
                onFrame={() => framePane(paneId)}
                onHeaderDoubleClick={() => framePane(paneId)}
                state={framedPaneId === paneId ? "framed" : "default"}
                title={paneId}
                titleId={titleIdForPane(paneId)}
              >
                {isRuler ? <LabRulerPane paneId={paneId} /> : <LabCardPane paneId={paneId} />}
              </PaneChrome>
            );
          }}
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
