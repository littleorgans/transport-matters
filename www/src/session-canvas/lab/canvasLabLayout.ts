import {
  type CanvasViewport,
  type EngineLayoutState,
  focusNode,
  type PaneId,
  type ViewportBounds,
} from "../../engine";
import type { LayoutParams } from "../../engine/layout";
import {
  DEFAULT_BOUNDS,
  INITIAL_STRATEGY_ID,
  openPaneIds,
  planLayout as planSharedLayout,
  SEED_RECT,
} from "../model/layoutPlanning";
import type { PaneContentRef } from "../model/paneRecords";
import { seedPaneFromRecord } from "../persistence/canvasPanePersistence";
import { planExpandLayout } from "./expandLayout";

export { DEFAULT_BOUNDS, INITIAL_STRATEGY_ID, openPaneIds };

const CLOSE_ZOOM_RESET_EPSILON = 0.001;

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

export function planLayout(
  layout: EngineLayoutState,
  bounds: ViewportBounds,
  activeStrategyId: string,
  params: LayoutParams,
  fitToContent: boolean,
  expandedPaneId: PaneId | null,
): EngineLayoutState {
  return planSharedLayout(
    layout,
    bounds,
    activeStrategyId,
    params,
    fitToContent,
    expandedPaneId,
    planExpandLayout,
  );
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
