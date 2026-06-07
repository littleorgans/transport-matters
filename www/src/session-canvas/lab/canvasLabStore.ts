import { create } from "zustand";
import {
  type CanvasViewport,
  clampScale,
  createInitialEngineLayoutState,
  createPaneNode,
  type EngineLayoutState,
  focusNode,
  frameRectViewport,
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
  type LayoutParams,
  listLayouts,
  type ParamValue,
  resolveLayout,
} from "../../engine/layout";

const DEFAULT_BOUNDS: ViewportBounds = { width: 1600, height: 1000 };
const SEED_RECT: WorldRect = { x: 48, y: 48, width: 360, height: 280 };
const FRAME_MS = 320;
const FIT_PADDING = 48; // Fit to content breathing room (matches the default world margin)
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

// Lab-side Fit to content: zoom the camera so the planned bounding box fits inside the viewport
// with a uniform FIT_PADDING of breathing room, only when it would otherwise overflow. Strategies
// never emit camera data (seam: strategies own rects, the camera owns the transform). Scale is
// computed against the padded inner frame but the box is centred in the full viewport.
function fitViewport(
  rects: Record<PaneId, WorldRect>,
  bounds: ViewportBounds,
): CanvasViewport | null {
  const box = boundingBox(rects);
  if (!box) return null;
  const innerW = bounds.width - 2 * FIT_PADDING;
  const innerH = bounds.height - 2 * FIT_PADDING;
  const rawScale = Math.min(innerW / box.width, innerH / box.height);
  if (rawScale >= 1) return null; // already fits inside the padded frame; do not zoom in
  const scale = clampScale(rawScale);
  const centerX = box.x + box.width / 2;
  const centerY = box.y + box.height / 2;
  return {
    scale,
    panX: bounds.width / 2 - centerX * scale,
    panY: bounds.height / 2 - centerY * scale,
  };
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
    set((state) => ({
      nextPaneIndex: index,
      layout: focusNode(
        upsertNode(state.layout, createPaneNode(paneId, SEED_RECT, nextPaneZ(state.layout.nodes))),
        paneId,
      ),
    }));
    get().organize();
  },

  closePane(paneId) {
    set((state) => ({ layout: removeNode(state.layout, paneId) }));
    get().organize();
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
    const { layout, bounds, activeStrategyId, params, fitToContent } = get();
    const { rects } = resolveLayout(activeStrategyId).plan(
      { paneIds: openPaneIds(layout), viewport: bounds },
      params,
    );
    let next = layout;
    for (const [paneId, rect] of Object.entries(rects)) {
      next = updateNodeRect(next, paneId, rect);
    }
    if (fitToContent) {
      const fitted = fitViewport(rects, bounds);
      if (fitted) next = setEngineViewport(next, fitted);
    }
    set({ layout: next });
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
