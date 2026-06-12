import { describe, expect, it } from "vitest";
import {
  createInitialEngineLayoutState,
  createPaneNode,
  removeNode,
  setViewport,
  upsertNode,
} from "../../engine";
import { registerLayout } from "../../engine/layout";
import { planLayout } from "./layoutPlanning";
import { emptyFraming, finalizePaneDismissal } from "./paneAffordances";

// Deterministic row-of-squares strategy so dismissal tests do not depend on
// gridFit math: pane i sits at x = i * 110.
registerLayout({
  id: "test-dismiss-row",
  label: "Dismiss fixture",
  controls: [],
  defaults: {},
  plan: ({ paneIds }) => ({
    rects: Object.fromEntries(
      paneIds.map((paneId, index) => [paneId, { x: index * 110, y: 0, width: 100, height: 100 }]),
    ),
  }),
});

const BOUNDS = { width: 800, height: 600 };

function threePaneState(viewport: { panX: number; panY: number; scale: number }) {
  let layout = createInitialEngineLayoutState();
  for (const id of ["a", "b", "c"]) layout = upsertNode(layout, createPaneNode(id, RECT, 1));
  layout = setViewport(layout, viewport);
  return {
    layout,
    bounds: BOUNDS,
    activeStrategyId: "test-dismiss-row",
    params: {},
    fitToContent: true,
    framing: emptyFraming(),
    expandedPaneId: null,
  };
}
const RECT = { x: 0, y: 0, width: 100, height: 100 };

function expectedOverview(state: ReturnType<typeof threePaneState>, paneId: string) {
  return planLayout(
    removeNode(state.layout, paneId),
    state.bounds,
    state.activeStrategyId,
    state.params,
    true,
  ).viewport;
}

describe("finalizePaneDismissal camera", () => {
  it("refits a stale wide camera to the new overview (close/minimize reflow)", () => {
    // camera zoomed OUT relative to what the remaining panes fit to: exactly
    // the bulk-close scenario where panes huddled at a stale zoom
    const state = threePaneState({ panX: 0, panY: 0, scale: 0.3 });

    const plan = finalizePaneDismissal(state, "c");

    expect(plan.layout.viewport).toEqual(expectedOverview(state, "c"));
    expect(plan.fly).toBe("camera");
  });

  it("still resets a zoomed-in camera to the overview", () => {
    const state = threePaneState({ panX: -200, panY: -100, scale: 3 });

    const plan = finalizePaneDismissal(state, "c");

    expect(plan.layout.viewport).toEqual(expectedOverview(state, "c"));
    expect(plan.fly).toBe("camera");
  });

  it("leaves an already-fitted camera alone with no camera fly", () => {
    const fitted = expectedOverview(threePaneState({ panX: 0, panY: 0, scale: 1 }), "c");
    const state = threePaneState(fitted);

    const plan = finalizePaneDismissal(state, "c");

    expect(plan.layout.viewport).toEqual(fitted);
    expect(plan.fly).toBe("none");
  });

  it("respects fitToContent off: a wide camera is the user's, keep it", () => {
    const state = { ...threePaneState({ panX: 12, panY: 34, scale: 0.3 }), fitToContent: false };

    const plan = finalizePaneDismissal(state, "c");

    // compare against the post-clamp stored viewport (the engine clamps scale)
    expect(plan.layout.viewport).toEqual(state.layout.viewport);
    expect(plan.fly).toBe("none");
  });
});
