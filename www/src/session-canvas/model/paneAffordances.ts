import {
  type CanvasViewport,
  CLOSE_DELAY_MS,
  DEFAULT_CANVAS_VIEWPORT,
  type EngineLayoutState,
  focusNode,
  frameRectViewport,
  markNodeClosing,
  type PaneId,
  removeNode,
  setViewport as setEngineViewport,
  type ViewportBounds,
} from "../../engine";
import type { LayoutParams } from "../../engine/layout";
import {
  type ExpandedLayoutPlanner,
  openPaneIds,
  planLayout,
  planSpawnedPaneLayout,
} from "./layoutPlanning";
import { resolvePaneLifecycle } from "./paneLifecycle";
import type { CanvasPaneRef, DockedPane, PaneRecord } from "./paneRecords";

const CLOSE_ZOOM_RESET_EPSILON = 0.001;

// Above this many open panes, unframe stops animating the camera and snaps straight to the overview:
// flying the scaled world back out re-rasterizes every pane each frame, which janks at scale.
export const UNFRAME_FLY_PANE_LIMIT = 60;

export type PaneDismissMode = "minimize" | "close";
export type PaneFlyIntent = "none" | "camera" | "pane-motion";

export interface FramingState {
  // Single-level framing. `paneId` is the framed pane (null at the overview). `overview` is the camera
  // snapshotted when framing began, restored on unframe. Framing a different pane while framed just
  // moves the camera and keeps the original overview, so unframe always pans back out to where the
  // user started. No nested frame history: stepping out of a frame returns to the overview, full stop.
  paneId: PaneId | null;
  overview: CanvasViewport | null;
}

export interface PaneAffordancePlanningState {
  layout: EngineLayoutState;
  bounds: ViewportBounds;
  activeStrategyId: string;
  params: LayoutParams;
  fitToContent: boolean;
  framing: FramingState;
  expandedPaneId: PaneId | null;
}

export interface PaneAffordanceTransition {
  layout: EngineLayoutState;
  framing: FramingState;
  expandedPaneId: PaneId | null;
  fly: PaneFlyIntent;
}

export type PaneAffordanceStateTransition = Omit<PaneAffordanceTransition, "fly">;

export interface PaneDismissalPlan extends PaneAffordanceTransition {}

interface PaneDismissStore<TState extends PaneAffordancePlanningState> {
  getState(): TState;
  setState(partial: Partial<TState> | ((state: TState) => Partial<TState>)): void;
}

interface DismissPaneOptions<TState extends PaneAffordancePlanningState> {
  paneId: PaneId;
  mode: PaneDismissMode;
  getRef(state: TState, paneId: PaneId): CanvasPaneRef | null;
  applyRemoval(
    state: TState,
    plan: PaneDismissalPlan,
    ref: CanvasPaneRef | null,
    mode: PaneDismissMode,
    paneId: PaneId,
  ): Partial<TState>;
  onFly?(intent: PaneFlyIntent): void;
  planExpandedLayout?: ExpandedLayoutPlanner;
}

export function dismissPane<TState extends PaneAffordancePlanningState>(
  store: PaneDismissStore<TState>,
  options: DismissPaneOptions<TState>,
): void {
  const { mode, paneId } = options;
  store.setState((state) => ({ layout: markNodeClosing(state.layout, paneId) }) as Partial<TState>);
  window.setTimeout(() => {
    const state = store.getState();
    const ref = options.getRef(state, paneId);
    invokePaneDismissLifecycle(ref, mode);
    const plan = finalizePaneDismissal(state, paneId, options.planExpandedLayout);
    options.onFly?.(plan.fly);
    store.setState(options.applyRemoval(state, plan, ref, mode, paneId));
  }, CLOSE_DELAY_MS);
}

export function emptyFraming(): FramingState {
  return { paneId: null, overview: null };
}

export function framedPaneId(framing: FramingState): PaneId | null {
  return framing.paneId;
}

export function stripPaneFlyIntent(
  transition: PaneAffordanceTransition,
): PaneAffordanceStateTransition {
  const { fly: _fly, ...stateTransition } = transition;
  return stateTransition;
}

export function commitPaneAffordanceTransition(
  transition: PaneAffordanceTransition | null,
  commit: (transition: PaneAffordanceStateTransition) => void,
  onFly?: (intent: PaneFlyIntent) => void,
): void {
  if (!transition) return;
  onFly?.(transition.fly);
  commit(stripPaneFlyIntent(transition));
}

export function closeDockedPaneWithLifecycle(
  docked: readonly DockedPane[],
  paneId: PaneId,
  options: { allowClose?: (entry: DockedPane) => boolean } = {},
): DockedPane[] | null {
  const entry = docked.find((candidate) => candidate.paneId === paneId);
  if (!entry || options.allowClose?.(entry) === false) return null;
  invokeDockedPaneCloseLifecycle(entry);
  return removeDockedPane(docked, paneId);
}

export function planAffordanceLayout(
  state: PaneAffordancePlanningState,
  fitToContent = state.fitToContent,
  expandedPaneId = state.expandedPaneId,
  planExpandedLayout?: ExpandedLayoutPlanner,
): EngineLayoutState {
  return planLayout(
    state.layout,
    state.bounds,
    state.activeStrategyId,
    state.params,
    fitToContent,
    expandedPaneId,
    planExpandedLayout,
  );
}

export function planSpawnedAffordancePaneLayout(
  state: PaneAffordancePlanningState,
  paneId: PaneId,
  planExpandedLayout?: ExpandedLayoutPlanner,
  focus = true,
  orderIndex?: number,
): EngineLayoutState {
  return planSpawnedPaneLayout(
    state,
    paneId,
    state.expandedPaneId,
    planExpandedLayout,
    focus,
    orderIndex,
  );
}

export function planPaneExpand(
  state: PaneAffordancePlanningState,
  paneId: PaneId,
  planExpandedLayout?: ExpandedLayoutPlanner,
): PaneAffordanceTransition | null {
  if (state.expandedPaneId === paneId) return planPaneUnexpand(state, planExpandedLayout);
  if (!state.layout.nodes[paneId]) return null;
  if (openPaneIds(state.layout).length <= 1) return null;
  return {
    expandedPaneId: paneId,
    framing: emptyFraming(),
    fly: "pane-motion",
    layout: planLayout(
      focusNode(state.layout, paneId),
      state.bounds,
      state.activeStrategyId,
      state.params,
      true,
      paneId,
      planExpandedLayout,
    ),
  };
}

export function planPaneUnexpand(
  state: PaneAffordancePlanningState,
  planExpandedLayout?: ExpandedLayoutPlanner,
): PaneAffordanceTransition | null {
  if (state.expandedPaneId === null) return null;
  return {
    expandedPaneId: null,
    framing: emptyFraming(),
    fly: "pane-motion",
    layout: planLayout(
      state.layout,
      state.bounds,
      state.activeStrategyId,
      state.params,
      true,
      null,
      planExpandedLayout,
    ),
  };
}

export function planPaneFrame(
  state: PaneAffordancePlanningState,
  paneId: PaneId,
): PaneAffordanceTransition | null {
  if (state.framing.paneId === paneId) return planPaneUnframe(state);
  const node = state.layout.nodes[paneId];
  if (!node) return null;
  if (openPaneIds(state.layout).length <= 1) return null;
  return {
    expandedPaneId: state.expandedPaneId,
    framing: {
      paneId,
      overview: state.framing.overview ?? state.layout.viewport,
    },
    fly: "camera",
    layout: focusNode(
      setEngineViewport(state.layout, frameRectViewport(node.rect, state.bounds)),
      paneId,
    ),
  };
}

export function planPaneUnframe(
  state: PaneAffordancePlanningState,
): PaneAffordanceTransition | null {
  if (state.framing.paneId === null) return null;
  return {
    expandedPaneId: state.expandedPaneId,
    framing: emptyFraming(),
    fly: openPaneIds(state.layout).length <= UNFRAME_FLY_PANE_LIMIT ? "camera" : "none",
    layout: setEngineViewport(state.layout, state.framing.overview ?? state.layout.viewport),
  };
}

export function finalizePaneDismissal(
  state: PaneAffordancePlanningState,
  paneId: PaneId,
  planExpandedLayout?: ExpandedLayoutPlanner,
): PaneDismissalPlan {
  const collapsing = state.expandedPaneId === paneId;
  const unframing = state.framing.paneId === paneId;
  const expandedPaneId = collapsing ? null : state.expandedPaneId;
  const framing = collapsing || unframing ? emptyFraming() : state.framing;
  const removed = removeNode(state.layout, paneId);
  let fly: PaneFlyIntent = "none";
  let layout = planLayout(
    removed,
    state.bounds,
    state.activeStrategyId,
    state.params,
    collapsing,
    expandedPaneId,
    planExpandedLayout,
  );
  if (collapsing) {
    fly = "pane-motion";
  } else if (unframing) {
    fly = "camera";
    layout = setEngineViewport(layout, state.framing.overview ?? DEFAULT_CANVAS_VIEWPORT);
  } else {
    const overviewLayout = planLayout(
      removed,
      state.bounds,
      state.activeStrategyId,
      state.params,
      true,
      expandedPaneId,
      planExpandedLayout,
    );
    // Two reasons to land at the new overview: a camera zoomed in past it
    // always resets (closing a zoomed pane restores the overview), and with
    // fit-to-content on, ANY stale camera refits — removing panes shrinks
    // the content box, so the new overview zooms IN relative to the old
    // wide camera and the zoom-reset check alone never fires, leaving the
    // replanned grid huddled at the stale zoom until a manual organize.
    // With fit-to-content off, a wide camera is the user's choice: keep it.
    const refit =
      isZoomedInPastOverview(state.layout.viewport, overviewLayout.viewport) ||
      (state.fitToContent && viewportDiffers(state.layout.viewport, overviewLayout.viewport));
    if (refit) {
      if (openPaneIds(layout).length <= UNFRAME_FLY_PANE_LIMIT) fly = "camera";
      layout = overviewLayout;
    }
  }
  return { expandedPaneId, framing, layout, fly };
}

const VIEWPORT_PAN_EPSILON_PX = 0.5;

function viewportDiffers(current: CanvasViewport, target: CanvasViewport): boolean {
  return (
    Math.abs(current.scale - target.scale) > CLOSE_ZOOM_RESET_EPSILON ||
    Math.abs(current.panX - target.panX) > VIEWPORT_PAN_EPSILON_PX ||
    Math.abs(current.panY - target.panY) > VIEWPORT_PAN_EPSILON_PX
  );
}

export function isZoomedInPastOverview(current: CanvasViewport, overview: CanvasViewport): boolean {
  return current.scale > overview.scale + CLOSE_ZOOM_RESET_EPSILON;
}

export function invokePaneDismissLifecycle(ref: CanvasPaneRef | null, mode: PaneDismissMode): void {
  if (!ref) return;
  const policy = resolvePaneLifecycle(ref);
  if (mode === "close") policy.onClose?.(ref);
  else policy.onMinimize?.(ref);
}

export function invokeDockedPaneRestoreLifecycle(entry: DockedPane): void {
  if (!entry.ref) return;
  resolvePaneLifecycle(entry.ref).onRestore?.(entry.ref);
}

export function invokeDockedPaneCloseLifecycle(entry: DockedPane): void {
  if (!entry.ref) return;
  resolvePaneLifecycle(entry.ref).onClose?.(entry.ref);
}

export function parkDockedPane(
  docked: readonly DockedPane[],
  paneId: PaneId,
  ref: CanvasPaneRef | null,
  record?: PaneRecord,
  closeDisabled = false,
): DockedPane[] {
  return [{ paneId, ref, record, closeDisabled }, ...removeDockedPane(docked, paneId)];
}

export function removeDockedPane(docked: readonly DockedPane[], paneId: PaneId): DockedPane[] {
  return docked.filter((entry) => entry.paneId !== paneId);
}

/**
 * The shared spawn contract both canvas stores honor: an already-open pane is
 * focused (or left alone), a docked pane is restored, anything else is seeded
 * fresh. Branch ordering lives here once so the stores cannot drift apart;
 * each store supplies its own lookups and seeding.
 */
export interface SpawnPaneFlow {
  isOpen(paneId: PaneId): boolean;
  focusPane(paneId: PaneId): void;
  isDocked(paneId: PaneId): boolean;
  restorePane(paneId: PaneId): void;
  seed(paneId: PaneId): void;
}

export function runSpawnPaneFlow(paneId: PaneId, focus: boolean, flow: SpawnPaneFlow): PaneId {
  if (flow.isOpen(paneId)) {
    if (focus) flow.focusPane(paneId);
    return paneId;
  }
  if (flow.isDocked(paneId)) {
    flow.restorePane(paneId);
    return paneId;
  }
  flow.seed(paneId);
  return paneId;
}

/**
 * The shared dock contract (terminal delivery parks the resource without
 * opening a pane): an OPEN pane minimizes through the dismiss flow, since it
 * is leaving the canvas and should animate and replan once; anything else
 * parks straight into the dock with NO layout mutation, so the grid never
 * resizes. parkDockedPane de-dupes and moves to front, which also covers the
 * already-docked case.
 */
export interface DockPaneFlow {
  isOpen(paneId: PaneId): boolean;
  minimizePane(paneId: PaneId): void;
  park(paneId: PaneId): void;
}

export function runDockPaneFlow(paneId: PaneId, flow: DockPaneFlow): PaneId {
  if (flow.isOpen(paneId)) {
    flow.minimizePane(paneId);
    return paneId;
  }
  flow.park(paneId);
  return paneId;
}
