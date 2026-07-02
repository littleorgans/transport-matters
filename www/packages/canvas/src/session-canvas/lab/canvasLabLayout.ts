import {
  type EngineLayoutState,
  focusNode,
  movePaneOrder,
  type PaneId,
  type ViewportBounds,
} from "../../engine";
import type { LayoutParams } from "../../engine/layout";
import { planExpandLayout } from "../model/expandLayout";
import {
  DEFAULT_BOUNDS,
  INITIAL_STRATEGY_ID,
  planLayout as planSharedLayout,
  SEED_RECT,
} from "../model/layoutPlanning";
import type { PaneContentRef } from "../model/paneRecords";
import { seedPaneFromRecord } from "../persistence/canvasPanePersistence";

export { DEFAULT_BOUNDS, INITIAL_STRATEGY_ID };

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

// Spawn a NEW pane: seed it at SEED_RECT through seedPaneFromRecord, focus it, then plan over the seeded
// layout in the SAME commit so it flies into its slot. Two separate sets (seed then organize) would flash
// the pane at SEED_RECT's corner for a frame first. Shared by addPane/addTerminal/addCapturedRun and the
// in-session restorePane, distinct from reload only in that reload skips replanning.
export function spawnPaneLayout(
  state: CanvasLabLayoutState,
  paneId: PaneId,
  ref: PaneContentRef | null,
  orderIndex?: number,
): Pick<CanvasLabLayoutState, "contentRefs" | "layout"> {
  const seeded = seedPaneFromRecord(state, paneId, ref, SEED_RECT);
  // Restore-at-index (doc 18): the seed appends, the splice moves, the plan
  // packs, all in the same commit, so the pane never flashes at the tail.
  const ordered =
    orderIndex === undefined ? seeded.layout : movePaneOrder(seeded.layout, paneId, orderIndex);
  return {
    contentRefs: seeded.contentRefs,
    layout: planLayout(
      focusNode(ordered, paneId),
      state.bounds,
      state.activeStrategyId,
      state.params,
      state.fitToContent,
      state.expandedPaneId,
    ),
  };
}
