import { useMemo, useState } from "react";
import {
  type CanvasViewport,
  createInitialEngineLayoutState,
  createPaneNode,
  type EngineLayoutState,
  LayoutCanvas,
  nextPaneZ,
  type PaneId,
  setViewport as setEngineViewport,
  updateNodeRect,
  upsertNode,
  type WorldRect,
} from "../../engine";
import { planEfficientLayout } from "../../engine/planners/efficientLayout";

const STRESS_COUNTS = [1, 2, 4, 8, 16, 30] as const;
const STRESS_VIEWPORT = { width: 1600, height: 1000 };

export function SessionCanvasStressRoute() {
  const [count, setCount] = useState<(typeof STRESS_COUNTS)[number]>(4);
  const [layout, setLayout] = useState(() => createStressLayout(count));
  const paneIds = useMemo(() => Object.keys(layout.nodes), [layout.nodes]);

  function applyCount(nextCount: (typeof STRESS_COUNTS)[number]): void {
    setCount(nextCount);
    setLayout(createStressLayout(nextCount));
  }

  return (
    <main className="canvas-route-shell">
      <div aria-label="Canvas stress controls" className="canvas-command-bar" role="toolbar">
        <div className="canvas-command-bar__identity">
          <span>FLIP stress harness</span>
          <span>{count} panes</span>
        </div>
        <div className="canvas-command-bar__buttons">
          {STRESS_COUNTS.map((option) => (
            <button
              className="canvas-button"
              key={option}
              onClick={() => applyCount(option)}
              type="button"
            >
              {option}
            </button>
          ))}
        </div>
      </div>
      <LayoutCanvas
        label="Session canvas stress harness"
        layout={layout}
        onFocusPane={(paneId) => setLayout((current) => ({ ...current, focusedPaneId: paneId }))}
        onMovePane={(paneId, rect) => setLayout((current) => updateNodeRect(current, paneId, rect))}
        onResizePane={(paneId, rect) =>
          setLayout((current) => updateNodeRect(current, paneId, rect))
        }
        renderPane={(paneId) => <SyntheticPane paneId={paneId} />}
        setViewport={(viewport: CanvasViewport) =>
          setLayout((current) => setEngineViewport(current, viewport))
        }
        titleIdForPane={(paneId) => `stress-title-${paneId}`}
      />
      <p className="canvas-stress-readout">Stable synthetic panes: {paneIds.length}</p>
    </main>
  );
}

function createStressLayout(count: number): EngineLayoutState {
  let layout = createInitialEngineLayoutState();
  const paneIds = Array.from({ length: count }, (_value, index) => `stress-${index + 1}`);
  const plan = planEfficientLayout({
    paneIds,
    currentRects: {},
    viewport: STRESS_VIEWPORT,
    mode: "floating",
    focusedPaneId: paneIds[0] ?? null,
  });
  for (const paneId of paneIds) {
    const rect = plan.rects[paneId] ?? fallbackRect(paneIds.indexOf(paneId));
    layout = upsertNode(layout, createPaneNode(paneId, rect, nextPaneZ(layout.nodes)));
  }
  return { ...layout, focusedPaneId: paneIds[0] ?? null };
}

function fallbackRect(index: number): WorldRect {
  return { x: 48 + index * 24, y: 48 + index * 24, width: 360, height: 280 };
}

function SyntheticPane({ paneId }: { paneId: PaneId }) {
  return (
    <article className="canvas-pane-window" data-focused="false" data-state="default">
      <header className="canvas-pane-window__header" data-pane-drag-handle="true">
        <div className="canvas-pane-window__title-wrap">
          <p className="canvas-pane-window__viewer">synthetic</p>
          <h2 className="canvas-pane-window__title" id={`stress-title-${paneId}`}>
            {paneId}
          </h2>
        </div>
      </header>
      <div className="canvas-pane-window__body">
        <div className="canvas-stress-card">Memoized synthetic content</div>
      </div>
      <div
        aria-hidden="true"
        className="canvas-pane-window__resize"
        data-pane-resize-handle="true"
      />
    </article>
  );
}
