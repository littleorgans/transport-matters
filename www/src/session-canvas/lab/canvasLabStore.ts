import { create } from "zustand";
import {
  type CanvasViewport,
  CLOSE_DELAY_MS,
  createInitialEngineLayoutState,
  createPaneNode,
  DEFAULT_CANVAS_VIEWPORT,
  type EngineLayoutState,
  focusNode,
  frameRectViewport,
  markNodeClosing,
  nextPaneZ,
  type PaneId,
  removeNode,
  setViewport as setEngineViewport,
  updateNodeRect,
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
  type ParamValue,
  resolveLayout,
} from "../../engine/layout";
import type { PaneContentRef } from "../model/paneRecords";
import { fitExpandFrameToWidth, planExpandedLayout } from "./expandLayout";

const DEFAULT_BOUNDS: ViewportBounds = { width: 1600, height: 1000 };
const SEED_RECT: WorldRect = { x: 48, y: 48, width: 360, height: 280 };
const FRAME_MS = 320;
const CLOSE_ZOOM_RESET_EPSILON = 0.001;
const INITIAL_STRATEGY_ID = BUILT_IN_CONFIGS[0]?.strategyId ?? listLayouts()[0]?.id ?? "grid-fit";
// Above this many open panes, unframe stops animating the camera and snaps straight to the overview:
// flying the scaled world back out re-rasterizes every pane each frame, which janks at scale.
export const UNFRAME_FLY_PANE_LIMIT = 60;

interface FramingState {
  // Single-level framing. `paneId` is the framed pane (null at the overview). `overview` is the camera
  // snapshotted when framing began, restored on unframe. Framing a different pane while framed just
  // moves the camera and keeps the original overview, so unframe always pans back out to where the
  // user started. No nested frame history: stepping out of a frame returns to the overview, full stop.
  paneId: PaneId | null;
  overview: CanvasViewport | null;
}

export function framedPaneId(framing: FramingState): PaneId | null {
  return framing.paneId;
}

export interface CanvasLabState {
  layout: EngineLayoutState;
  bounds: ViewportBounds;
  activeStrategyId: string;
  params: LayoutParams;
  fitToContent: boolean;
  framing: FramingState;
  expandedPaneId: PaneId | null;
  flying: boolean;
  paneMotion: boolean;
  nextPaneIndex: number;
  /** Real content per pane (a viewer-registry ref). Demo card/ruler panes carry none. */
  contentRefs: Record<PaneId, PaneContentRef>;
  addPane(): void;
  addTerminal(): void;
  closePane(paneId: PaneId): void;
  focusPane(paneId: PaneId): void;
  updatePaneRect(paneId: PaneId, rect: WorldRect): void;
  setStrategy(strategyId: string): void;
  setParam(key: string, value: ParamValue): void;
  setFitToContent(on: boolean): void;
  organize(): void;
  setBounds(bounds: ViewportBounds): void;
  expandPane(paneId: PaneId): void;
  unexpand(): void;
  framePane(paneId: PaneId): void;
  unframe(): void;
  resetView(): void;
  setViewport(viewport: CanvasViewport): void;
}

function openPaneIds(layout: EngineLayoutState): PaneId[] {
  return Object.values(layout.nodes)
    .filter((node) => node.lifecycle === "open")
    .map((node) => node.paneId);
}

function seedParams(strategyId: string): LayoutParams {
  return { ...resolveLayout(strategyId).defaults };
}

// Returns a valid, in-range value, or undefined when the (key, value) is not a valid edit for the
// active strategy (unknown key, wrong runtime type, or out-of-range enum) so setParam ignores it.
function sanitizeParam(strategyId: string, key: string, value: ParamValue): ParamValue | undefined {
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
function planLayout(
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

function isZoomedInPastOverview(current: CanvasViewport, overview: CanvasViewport): boolean {
  return current.scale > overview.scale + CLOSE_ZOOM_RESET_EPSILON;
}

// Born at its planned slot in a single commit: seed the node, then plan over the seeded layout in the
// SAME set. Two separate sets (seed then organize) would render the pane at SEED_RECT's top-left corner
// for one frame before springing to its slot (the "fly in from top-left"). Shared by addPane/addTerminal.
function seedPaneLayout(state: CanvasLabState, paneId: PaneId): EngineLayoutState {
  const seeded = focusNode(
    upsertNode(state.layout, createPaneNode(paneId, SEED_RECT, nextPaneZ(state.layout.nodes))),
    paneId,
  );
  return planLayout(
    seeded,
    state.bounds,
    state.activeStrategyId,
    state.params,
    state.fitToContent,
    state.expandedPaneId,
  );
}

export const useCanvasLabStore = create<CanvasLabState>()((set, get) => ({
  layout: createInitialEngineLayoutState(),
  bounds: DEFAULT_BOUNDS,
  activeStrategyId: INITIAL_STRATEGY_ID,
  params: seedParams(INITIAL_STRATEGY_ID),
  fitToContent: true,
  framing: { paneId: null, overview: null },
  expandedPaneId: null,
  flying: false,
  paneMotion: false,
  nextPaneIndex: 0,
  contentRefs: {},

  addPane() {
    const index = get().nextPaneIndex + 1;
    set((state) => ({ nextPaneIndex: index, layout: seedPaneLayout(state, `lab-${index}`) }));
  },

  addTerminal() {
    const index = get().nextPaneIndex + 1;
    const paneId = `lab-${index}`;
    set((state) => ({
      nextPaneIndex: index,
      contentRefs: { ...state.contentRefs, [paneId]: { kind: "terminal", owner: "local" } },
      layout: seedPaneLayout(state, paneId),
    }));
  },

  closePane(paneId) {
    // Two-phase close so the exit reads cleanly: mark the pane closing (PaneFrame fades + scales it
    // out in place, neighbours hold their slots), then after the exit window remove it and re-plan so
    // the survivors flow in to fill the gap. Mirrors the production canvasStore close protocol.
    set((state) => ({ layout: markNodeClosing(state.layout, paneId) }));
    window.setTimeout(() => {
      const state = get();
      const collapsing = state.expandedPaneId === paneId;
      const unframing = state.framing.paneId === paneId;
      const expandedPaneId = collapsing ? null : state.expandedPaneId;
      const framing = collapsing || unframing ? { paneId: null, overview: null } : state.framing;
      const removed = removeNode(state.layout, paneId);
      let layout = planLayout(
        removed,
        state.bounds,
        state.activeStrategyId,
        state.params,
        collapsing,
        expandedPaneId,
      );
      if (collapsing) {
        startFly({ paneMotion: true });
      } else if (unframing) {
        startFly();
        layout = setEngineViewport(layout, state.framing.overview ?? DEFAULT_CANVAS_VIEWPORT);
      } else {
        const overviewLayout = planLayout(
          removed,
          state.bounds,
          state.activeStrategyId,
          state.params,
          true,
          expandedPaneId,
        );
        if (isZoomedInPastOverview(state.layout.viewport, overviewLayout.viewport)) {
          if (openPaneIds(layout).length <= UNFRAME_FLY_PANE_LIMIT) startFly();
          layout = overviewLayout;
        }
      }
      const { [paneId]: _closed, ...contentRefs } = state.contentRefs;
      set({
        expandedPaneId,
        framing,
        contentRefs,
        // Reflow survivors into the gap. A fitted close is reserved for exiting expand mode, leaving a
        // frame, or undoing manual zoom-in; normal overview and zoomed-out closes keep the camera stable.
        layout,
      });
    }, CLOSE_DELAY_MS);
  },

  focusPane(paneId) {
    set((state) => ({ layout: focusNode(state.layout, paneId) }));
  },

  updatePaneRect(paneId, rect) {
    set((state) => ({ layout: updateNodeRect(state.layout, paneId, rect) }));
  },

  setStrategy(strategyId) {
    set({ activeStrategyId: strategyId, params: seedParams(strategyId) });
    get().organize();
  },

  setParam(key, value) {
    const sanitized = sanitizeParam(get().activeStrategyId, key, value);
    if (sanitized === undefined) return; // ignore unknown keys / wrong types / bad enum values
    set((state) => ({ params: { ...state.params, [key]: sanitized } }));
    get().organize();
  },

  setFitToContent(on) {
    set({ fitToContent: on });
    get().organize();
  },

  organize() {
    set((state) => ({
      layout: planLayout(
        state.layout,
        state.bounds,
        state.activeStrategyId,
        state.params,
        state.fitToContent,
        state.expandedPaneId,
      ),
    }));
  },

  setBounds(bounds) {
    set({ bounds });
    get().organize();
  },

  expandPane(paneId) {
    const { layout, expandedPaneId } = get();
    if (expandedPaneId === paneId) {
      get().unexpand();
      return;
    }
    if (!layout.nodes[paneId]) return;
    if (openPaneIds(layout).length <= 1) return;
    startFly({ paneMotion: true });
    set((state) => ({
      expandedPaneId: paneId,
      framing: { paneId: null, overview: null },
      layout: planLayout(
        focusNode(state.layout, paneId),
        state.bounds,
        state.activeStrategyId,
        state.params,
        true,
        paneId,
      ),
    }));
  },

  unexpand() {
    if (get().expandedPaneId === null) return;
    startFly({ paneMotion: true });
    set((state) => ({
      expandedPaneId: null,
      framing: { paneId: null, overview: null },
      layout: planLayout(
        state.layout,
        state.bounds,
        state.activeStrategyId,
        state.params,
        true,
        null,
      ),
    }));
  },

  framePane(paneId) {
    const { layout, bounds, framing } = get();
    // Re-framing the current pane toggles it off.
    if (framing.paneId === paneId) {
      get().unframe();
      return;
    }
    if (openPaneIds(layout).length <= 1) return;
    const node = layout.nodes[paneId];
    if (!node) return;
    startFly();
    set((state) => ({
      framing: {
        paneId,
        // Snapshot the pre-framing camera only when entering from the overview; switching frames keeps
        // it so unframe still pans back out to where the user started, not to the previous frame.
        overview: state.framing.overview ?? state.layout.viewport,
      },
      // Frame the pane and select it (white border).
      layout: focusNode(
        setEngineViewport(state.layout, frameRectViewport(node.rect, bounds)),
        paneId,
      ),
    }));
  },

  unframe() {
    const { framing, layout } = get();
    if (framing.paneId === null) return;
    // Pan back out to the overview captured when framing began. Above the pane limit the camera snaps
    // instead of flying, since animating the scaled world back out re-rasterizes every pane per frame.
    if (openPaneIds(layout).length <= UNFRAME_FLY_PANE_LIMIT) startFly();
    set((state) => ({
      framing: { paneId: null, overview: null },
      layout: setEngineViewport(state.layout, state.framing.overview ?? state.layout.viewport),
    }));
  },

  resetView() {
    startFly();
    set((state) => ({
      framing: { paneId: null, overview: null },
      expandedPaneId: null,
      layout: setEngineViewport(state.layout, { panX: 0, panY: 0, scale: 1 }),
    }));
  },

  setViewport(viewport) {
    set((state) => ({ layout: setEngineViewport(state.layout, viewport) }));
  },
}));

let flyTimer: number | null = null;

interface FlyOptions {
  paneMotion?: boolean;
}

// Brief transition flags for camera fly and opt-in pane geometry motion.
function startFly(options: FlyOptions = {}): void {
  useCanvasLabStore.setState({
    flying: true,
    paneMotion: options.paneMotion ?? false,
  });
  if (flyTimer !== null) window.clearTimeout(flyTimer);
  flyTimer = window.setTimeout(() => {
    flyTimer = null;
    useCanvasLabStore.setState({ flying: false, paneMotion: false });
  }, FRAME_MS);
}

export function resetCanvasLabStoreForTests(): void {
  if (flyTimer !== null) window.clearTimeout(flyTimer);
  flyTimer = null;
  useCanvasLabStore.setState({
    layout: createInitialEngineLayoutState(),
    bounds: DEFAULT_BOUNDS,
    activeStrategyId: INITIAL_STRATEGY_ID,
    params: seedParams(INITIAL_STRATEGY_ID),
    fitToContent: true,
    framing: { paneId: null, overview: null },
    expandedPaneId: null,
    flying: false,
    paneMotion: false,
    nextPaneIndex: 0,
    contentRefs: {},
  });
}
