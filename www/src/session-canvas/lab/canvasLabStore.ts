import { create } from "zustand";
import {
  type CanvasViewport,
  CLOSE_DELAY_MS,
  createInitialEngineLayoutState,
  createPaneNode,
  type EngineLayoutState,
  focusNode,
  frameRectViewport,
  markNodeClosing,
  nextPaneZ,
  type PaneId,
  removeNode,
  setViewport as setEngineViewport,
  updateNodeRect,
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

const DEFAULT_BOUNDS: ViewportBounds = { width: 1600, height: 1000 };
const SEED_RECT: WorldRect = { x: 48, y: 48, width: 360, height: 280 };
const FRAME_MS = 320;
const INITIAL_STRATEGY_ID = BUILT_IN_CONFIGS[0]?.strategyId ?? listLayouts()[0]?.id ?? "grid-fit";

interface FramingState {
  framedPaneId: PaneId | null;
  priorViewport: CanvasViewport | null;
}

export interface CanvasLabState {
  layout: EngineLayoutState;
  bounds: ViewportBounds;
  activeStrategyId: string;
  params: LayoutParams;
  fitToContent: boolean;
  framing: FramingState;
  flying: boolean;
  nextPaneIndex: number;
  addPane(): void;
  closePane(paneId: PaneId): void;
  focusPane(paneId: PaneId): void;
  updatePaneRect(paneId: PaneId, rect: WorldRect): void;
  setStrategy(strategyId: string): void;
  setParam(key: string, value: ParamValue): void;
  setFitToContent(on: boolean): void;
  organize(): void;
  setBounds(bounds: ViewportBounds): void;
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
): EngineLayoutState {
  const { rects, frame } = resolveLayout(activeStrategyId).plan(
    { paneIds: openPaneIds(layout), viewport: bounds },
    params,
  );
  let next = layout;
  for (const [paneId, rect] of Object.entries(rects)) {
    next = updateNodeRect(next, paneId, rect);
  }
  if (fitToContent) {
    const fitted = fitViewport(rects, bounds, frame);
    if (fitted) next = setEngineViewport(next, fitted);
  }
  return next;
}

export const useCanvasLabStore = create<CanvasLabState>()((set, get) => ({
  layout: createInitialEngineLayoutState(),
  bounds: DEFAULT_BOUNDS,
  activeStrategyId: INITIAL_STRATEGY_ID,
  params: seedParams(INITIAL_STRATEGY_ID),
  fitToContent: true,
  framing: { framedPaneId: null, priorViewport: null },
  flying: false,
  nextPaneIndex: 0,

  addPane() {
    const index = get().nextPaneIndex + 1;
    const paneId = `lab-${index}`;
    // Born at its planned slot in a single commit: seed the node, then plan over the seeded layout
    // in the SAME set. Two separate sets (seed then organize) would render the pane at SEED_RECT's
    // top-left corner for one frame before springing to its slot (the "fly in from top-left").
    set((state) => {
      const seeded = focusNode(
        upsertNode(state.layout, createPaneNode(paneId, SEED_RECT, nextPaneZ(state.layout.nodes))),
        paneId,
      );
      return {
        nextPaneIndex: index,
        layout: planLayout(
          seeded,
          state.bounds,
          state.activeStrategyId,
          state.params,
          state.fitToContent,
        ),
      };
    });
  },

  closePane(paneId) {
    // Two-phase close so the exit reads cleanly: mark the pane closing (PaneFrame fades + scales it
    // out in place, neighbours hold their slots), then after the exit window remove it and re-plan so
    // the survivors flow in to fill the gap. Mirrors the production canvasStore close protocol.
    set((state) => ({ layout: markNodeClosing(state.layout, paneId) }));
    window.setTimeout(() => {
      set((state) => ({
        layout: planLayout(
          removeNode(state.layout, paneId),
          state.bounds,
          state.activeStrategyId,
          state.params,
          state.fitToContent,
        ),
      }));
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
      ),
    }));
  },

  setBounds(bounds) {
    set({ bounds });
    get().organize();
  },

  framePane(paneId) {
    const { layout, bounds, framing } = get();
    if (framing.framedPaneId === paneId) {
      get().unframe();
      return;
    }
    if (openPaneIds(layout).length <= 1) return;
    const node = layout.nodes[paneId];
    if (!node) return;
    startFly();
    set((state) => ({
      framing: { framedPaneId: paneId, priorViewport: state.layout.viewport },
      layout: setEngineViewport(state.layout, frameRectViewport(node.rect, bounds)),
    }));
  },

  unframe() {
    const prior = get().framing.priorViewport;
    if (!prior) {
      set({ framing: { framedPaneId: null, priorViewport: null } });
      return;
    }
    startFly();
    set((state) => ({
      framing: { framedPaneId: null, priorViewport: null },
      layout: setEngineViewport(state.layout, prior),
    }));
  },

  resetView() {
    startFly();
    set((state) => ({
      framing: { framedPaneId: null, priorViewport: null },
      layout: setEngineViewport(state.layout, { panX: 0, panY: 0, scale: 1 }),
    }));
  },

  setViewport(viewport) {
    set((state) => ({ layout: setEngineViewport(state.layout, viewport) }));
  },
}));

let flyTimer: number | null = null;

// Brief transform-transition flag for the camera "fly" on frame/unframe/reset.
function startFly(): void {
  useCanvasLabStore.setState({ flying: true });
  if (flyTimer !== null) window.clearTimeout(flyTimer);
  flyTimer = window.setTimeout(() => {
    flyTimer = null;
    useCanvasLabStore.setState({ flying: false });
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
    framing: { framedPaneId: null, priorViewport: null },
    flying: false,
    nextPaneIndex: 0,
  });
}
