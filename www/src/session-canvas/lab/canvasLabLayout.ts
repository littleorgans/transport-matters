import {
  type CanvasViewport,
  type EngineLayoutState,
  focusNode,
  type PaneId,
  setViewport as setEngineViewport,
  updateNodeRects,
  type ViewportBounds,
  type WorldRect,
} from "../../engine";
import {
  BUILT_IN_CONFIGS,
  fitScale,
  type LayoutParams,
  listLayouts,
  type ParamValue,
  resolveLayout,
} from "../../engine/layout";
import type { PaneContentRef } from "../model/paneRecords";
import { seedPaneFromRecord } from "./canvasLabStore.persistence";
import { fitExpandFrameToWidth, planExpandedLayout } from "./expandLayout";

export const DEFAULT_BOUNDS: ViewportBounds = { width: 1600, height: 1000 };
const SEED_RECT: WorldRect = { x: 48, y: 48, width: 360, height: 280 };
const CLOSE_ZOOM_RESET_EPSILON = 0.001;
export const INITIAL_STRATEGY_ID =
  BUILT_IN_CONFIGS[0]?.strategyId ?? listLayouts()[0]?.id ?? "grid-fit";

// Above this many open panes, unframe stops animating the camera and snaps straight to the overview:
// flying the scaled world back out re-rasterizes every pane each frame, which janks at scale.
export const UNFRAME_FLY_PANE_LIMIT = 60;

interface CanvasLabLayoutState {
  layout: EngineLayoutState;
  bounds: ViewportBounds;
  activeStrategyId: string;
  params: LayoutParams;
  fitToContent: boolean;
  expandedPaneId: PaneId | null;
  contentRefs: Record<PaneId, PaneContentRef>;
}

export function openPaneIds(layout: EngineLayoutState): PaneId[] {
  return Object.values(layout.nodes)
    .filter((node) => node.lifecycle === "open")
    .map((node) => node.paneId);
}

export function seedParams(strategyId: string): LayoutParams {
  return { ...resolveLayout(strategyId).defaults };
}

// Returns a valid, in-range value, or undefined when the (key, value) is not a valid edit for the
// active strategy (unknown key, wrong runtime type, or out-of-range enum) so setParam ignores it.
export function sanitizeParam(
  strategyId: string,
  key: string,
  value: ParamValue,
): ParamValue | undefined {
  const control = resolveLayout(strategyId).controls.find((entry) => entry.key === key);
  if (!control) return undefined; // unknown key
  if (control.kind === "number") {
    if (typeof value !== "number" || !Number.isFinite(value)) return undefined;
    return Math.min(control.max, Math.max(control.min, value));
  }
  if (control.kind === "toggle") {
    return typeof value === "boolean" ? value : undefined;
  }
  if (typeof value !== "string") return undefined;
  return control.options.some((option) => option.value === value) ? value : undefined;
}

function boundingBox(rects: Record<PaneId, WorldRect>): WorldRect | null {
  const values = Object.values(rects);
  if (values.length === 0) return null;
  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  for (const rect of values) {
    minX = Math.min(minX, rect.x);
    minY = Math.min(minY, rect.y);
    maxX = Math.max(maxX, rect.x + rect.width);
    maxY = Math.max(maxY, rect.y + rect.height);
  }
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
}

// Lab-side Fit to content: zoom the camera so the planned content fits inside the viewport, only
// when it would otherwise overflow. Frames the strategy's `frame` rect when it supplies one (e.g.
// grid-fit pads its grid by `margin` so that margin survives as on-screen breathing room) and falls
// back to the rect bounding box otherwise. Uses the SAME shared fitScale the planner simulates when
// choosing its column count, so the two can never drift. Strategies never emit camera transforms
// (seam: strategies own geometry, the camera owns the transform). setEngineViewport applies the
// engine clampScale bounds when the result is committed.
function fitViewport(
  rects: Record<PaneId, WorldRect>,
  bounds: ViewportBounds,
  frame?: WorldRect,
): CanvasViewport | null {
  const box = frame ?? boundingBox(rects);
  if (!box) return null; // no panes: leave the camera untouched
  // fitScale caps at 1 (never magnify). Always recompute and commit so a zoomed-out transform from a
  // smaller bounds/pane-count can never persist as stale slack once the content fits again.
  const scale = fitScale(box.width, box.height, bounds);
  const centerX = box.x + box.width / 2;
  const centerY = box.y + box.height / 2;
  return {
    scale,
    panX: bounds.width / 2 - centerX * scale,
    panY: bounds.height / 2 - centerY * scale,
  };
}

// Pure planner: run the active strategy over the open panes, write every planned rect back, and
// (when fitToContent) recompute the fit camera. Shared by organize() and addPane() so the new pane
// can be planned into its final slot within a single store commit. No get/set: callers own the set.
export function planLayout(
  layout: EngineLayoutState,
  bounds: ViewportBounds,
  activeStrategyId: string,
  params: LayoutParams,
  fitToContent: boolean,
  expandedPaneId: PaneId | null,
): EngineLayoutState {
  const paneIds = openPaneIds(layout);
  if (expandedPaneId && paneIds.includes(expandedPaneId)) {
    const { rects, frame } = planExpandedLayout({ paneIds, expandedPaneId, viewport: bounds });
    let next = updateNodeRects(layout, rects);
    if (fitToContent) {
      next = setEngineViewport(next, fitExpandFrameToWidth(frame, bounds));
    }
    return next;
  }

  const { rects, frame } = resolveLayout(activeStrategyId).plan(
    { paneIds, viewport: bounds },
    params,
  );
  let next = updateNodeRects(layout, rects);
  if (fitToContent) {
    const fitted = fitViewport(rects, bounds, frame);
    if (fitted) next = setEngineViewport(next, fitted);
  }
  return next;
}

export function isZoomedInPastOverview(current: CanvasViewport, overview: CanvasViewport): boolean {
  return current.scale > overview.scale + CLOSE_ZOOM_RESET_EPSILON;
}

// Spawn a NEW pane: seed it at SEED_RECT through seedPaneFromRecord, focus it, then plan over the seeded
// layout in the SAME commit so it flies into its slot. Two separate sets (seed then organize) would flash
// the pane at SEED_RECT's corner for a frame first. Shared by addPane/addTerminal/addCapturedRun and the
// in-session restorePane, distinct from reload only in that reload skips replanning.
export function spawnPaneLayout(
  state: CanvasLabLayoutState,
  paneId: PaneId,
  ref: PaneContentRef | null,
): Pick<CanvasLabLayoutState, "contentRefs" | "layout"> {
  const seeded = seedPaneFromRecord(state, paneId, ref, SEED_RECT);
  return {
    contentRefs: seeded.contentRefs,
    layout: planLayout(
      focusNode(seeded.layout, paneId),
      state.bounds,
      state.activeStrategyId,
      state.params,
      state.fitToContent,
      state.expandedPaneId,
    ),
  };
}
