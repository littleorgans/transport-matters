import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { FrameMeter, type FrameMeterSummary } from "../../engine/perf/frameMeter";
import { planEfficientLayout } from "../../engine/planners/efficientLayout";

const STRESS_COUNTS = [1, 2, 4, 8, 16, 30] as const;
const STRESS_VIEWPORT = { width: 1600, height: 1000 };
const STRESS_CAPTURE_MS = 1_200;

type StressAction = "spawn" | "close" | "focus" | "drag" | "resize" | "pan" | "zoom";

interface StressMeasurement {
  action: StressAction;
  summary: FrameMeterSummary;
}

export function SessionCanvasStressRoute() {
  const [count, setCount] = useState<(typeof STRESS_COUNTS)[number]>(4);
  const [layout, setLayout] = useState(() => createStressLayout(count));
  const { measure, measurement } = useStressFrameMeter();
  const paneIds = useMemo(() => Object.keys(layout.nodes), [layout.nodes]);

  function applyCount(nextCount: (typeof STRESS_COUNTS)[number]): void {
    const action = nextCount >= count ? "spawn" : "close";
    measure(action, () => {
      setCount(nextCount);
      setLayout(createStressLayout(nextCount));
    });
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
        onFocusPane={(paneId) =>
          measure("focus", () => setLayout((current) => ({ ...current, focusedPaneId: paneId })))
        }
        onMovePane={(paneId, rect) =>
          measure("drag", () => setLayout((current) => updateNodeRect(current, paneId, rect)))
        }
        onResizePane={(paneId, rect) =>
          measure("resize", () => setLayout((current) => updateNodeRect(current, paneId, rect)))
        }
        renderPane={(paneId) => <SyntheticPane paneId={paneId} />}
        setViewport={(viewport: CanvasViewport) =>
          measure(viewport.scale === layout.viewport.scale ? "pan" : "zoom", () =>
            setLayout((current) => setEngineViewport(current, viewport)),
          )
        }
        titleIdForPane={(paneId) => `stress-title-${paneId}`}
      />
      <p
        className="canvas-stress-readout"
        data-stress-action={measurement?.action ?? "idle"}
        data-stress-frames={measurement?.summary.frames ?? 0}
        data-stress-max-frame={measurement?.summary.maxDeltaMs.toFixed(2) ?? "0.00"}
        data-stress-p95-frame={measurement?.summary.p95DeltaMs.toFixed(2) ?? "0.00"}
      >
        Stable synthetic panes: {paneIds.length}
        {measurement
          ? ` · ${measurement.action} p95 ${measurement.summary.p95DeltaMs.toFixed(2)}ms across ${measurement.summary.frames} frames`
          : " · awaiting motion sample"}
      </p>
    </main>
  );
}

function useStressFrameMeter(): {
  measure(action: StressAction, update: () => void): void;
  measurement: StressMeasurement | null;
} {
  const [measurement, setMeasurement] = useState<StressMeasurement | null>(null);
  const meterRef = useRef(new FrameMeter());
  const timerRef = useRef<number | null>(null);

  const measure = useCallback((action: StressAction, update: () => void) => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    const meter = meterRef.current;
    meter.reset();
    meter.start();
    update();
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      setMeasurement({ action, summary: meter.stop() });
    }, STRESS_CAPTURE_MS);
  }, []);

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
      meterRef.current.stop();
    };
  }, []);

  return { measure, measurement };
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

const SyntheticPane = memo(function SyntheticPane({ paneId }: { paneId: PaneId }) {
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
});
