import {
  type CanvasViewport,
  createPaneNode,
  type EngineLayoutState,
  focusNode,
  nextPaneZ,
  type PaneId,
  setViewport as setEngineViewport,
  updateNodeRects,
  upsertNode,
  type ViewportBounds,
  type WorldRect,
} from "../../engine";
import {
  BUILT_IN_CONFIGS,
  fitScale,
  type LayoutParams,
  listLayouts,
  type PlanInput,
  type PlanResult,
  resolveLayout,
} from "../../engine/layout";

export const DEFAULT_BOUNDS: ViewportBounds = { width: 1600, height: 1000 };
export const SEED_RECT: WorldRect = { x: 48, y: 48, width: 360, height: 280 };
export const INITIAL_STRATEGY_ID =
  BUILT_IN_CONFIGS[0]?.strategyId ?? listLayouts()[0]?.id ?? "grid-fit";

export interface LayoutPlanningState {
  layout: EngineLayoutState;
  bounds: ViewportBounds;
  activeStrategyId: string;
  params: LayoutParams;
  fitToContent: boolean;
}

export interface CameraPlanResult extends PlanResult {
  camera?: CanvasViewport;
}

export type ExpandedLayoutPlanner = (
  input: PlanInput & { expandedPaneId: PaneId },
) => CameraPlanResult;

export function openPaneIds(layout: EngineLayoutState): PaneId[] {
  return layout.order.filter((paneId) => layout.nodes[paneId]?.lifecycle === "open");
}

export function seedPaneLayout(layout: EngineLayoutState, paneId: PaneId): EngineLayoutState {
  return upsertNode(layout, createPaneNode(paneId, SEED_RECT, nextPaneZ(layout.nodes)));
}

export function planSpawnedPaneLayout(
  state: LayoutPlanningState,
  paneId: PaneId,
  expandedPaneId: PaneId | null = null,
  planExpandedLayout?: ExpandedLayoutPlanner,
  focus = true,
): EngineLayoutState {
  const seeded = seedPaneLayout(state.layout, paneId);
  return planLayout(
    focus ? focusNode(seeded, paneId) : seeded,
    state.bounds,
    state.activeStrategyId,
    state.params,
    state.fitToContent,
    expandedPaneId,
    planExpandedLayout,
  );
}

export function planLayout(
  layout: EngineLayoutState,
  bounds: ViewportBounds,
  activeStrategyId: string,
  params: LayoutParams,
  fitToContent: boolean,
  expandedPaneId: PaneId | null = null,
  planExpandedLayout?: ExpandedLayoutPlanner,
  paneIdsOverride?: readonly PaneId[],
): EngineLayoutState {
  const paneIds = paneIdsOverride ? [...paneIdsOverride] : openPaneIds(layout);
  const planned: CameraPlanResult =
    expandedPaneId && paneIds.includes(expandedPaneId) && planExpandedLayout
      ? planExpandedLayout({ paneIds, expandedPaneId, viewport: bounds })
      : resolveLayout(activeStrategyId).plan({ paneIds, viewport: bounds }, params);
  let next = updateNodeRects(layout, planned.rects);
  if (fitToContent) {
    const fitted = planned.camera ?? fitViewport(planned.rects, bounds, planned.frame);
    if (fitted) next = setEngineViewport(next, fitted);
  }
  return next;
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

function fitViewport(
  rects: Record<PaneId, WorldRect>,
  bounds: ViewportBounds,
  frame?: WorldRect,
): CanvasViewport | null {
  const box = frame ?? boundingBox(rects);
  if (!box) return null;
  const scale = fitScale(box.width, box.height, bounds);
  const centerX = box.x + box.width / 2;
  const centerY = box.y + box.height / 2;
  return {
    scale,
    panX: bounds.width / 2 - centerX * scale,
    panY: bounds.height / 2 - centerY * scale,
  };
}
