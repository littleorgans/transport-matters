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
import type { CliName } from "../../types";
import { resolvePaneLifecycle } from "../model/paneLifecycle";
import { cliLabel, type DockedPane, type PaneContentRef } from "../model/paneRecords";
import { createCapturedRunKey } from "./capturedRunStore";
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
  /** Locally minimized panes for THIS canvas, most-recent first. The dock's only source. */
  docked: DockedPane[];
  /** Monotonic per-label-prefix counters so spawned content panes get incremental names
   *  (Terminal-1, Claude-2, Codex-3) like demo panes get lab-N. Never reused on close. */
  paneCounters: Record<string, number>;
  addPane(): void;
  addTerminal(): void;
  addCapturedRun(provider: CliName): void;
  /** Recreate a captured pane at its persisted key on reload so it re-attaches by id. */
  restoreCapturedPane(paneId: PaneId, provider: CliName): void;
  /** Minimize ([-]): park the pane in the dock and remove it. Generic — runs the kind's onMinimize hook (captured keeps its run alive). */
  minimizePane(paneId: PaneId): void;
  /** Close ([X]): remove the pane and run the kind's onClose hook (captured-run kills the run via DELETE). */
  closePane(paneId: PaneId): void;
  /** Restore a docked pane: re-seed it at its original id so its viewer re-mounts (captured re-attaches by run id). */
  restorePane(paneId: PaneId): void;
  /** Close/kill a docked pane WITHOUT restoring it: run its onClose hook (captured-run kills the run) and drop the dock entry. */
  closeDockedPane(paneId: PaneId): void;
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

/** Seed a lab pane with an explicit id carrying a viewer-registry content ref. */
function seedContentPane(
  state: CanvasLabState,
  paneId: PaneId,
  ref: PaneContentRef,
): Pick<CanvasLabState, "contentRefs" | "layout"> {
  return {
    contentRefs: { ...state.contentRefs, [paneId]: ref },
    layout: seedPaneLayout(state, paneId),
  };
}

// Next incremental label for a prefix ("Terminal" | "Claude" | "Codex"), plus the bumped counter
// map. Monotonic and never reused on close, mirroring nextPaneIndex's lab-N scheme.
function labelFor(
  counters: Record<string, number>,
  prefix: string,
): { label: string; counters: Record<string, number> } {
  const next = (counters[prefix] ?? 0) + 1;
  return { label: `${prefix}-${next}`, counters: { ...counters, [prefix]: next } };
}

/** Seed a new lab pane carrying a viewer-registry content ref, advancing the pane index. */
function spawnContentPane(
  state: CanvasLabState,
  ref: PaneContentRef,
): Pick<CanvasLabState, "nextPaneIndex" | "contentRefs" | "layout"> {
  const index = state.nextPaneIndex + 1;
  return { nextPaneIndex: index, ...seedContentPane(state, `lab-${index}`, ref) };
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
  docked: [],
  paneCounters: {},

  addPane() {
    const index = get().nextPaneIndex + 1;
    set((state) => ({ nextPaneIndex: index, layout: seedPaneLayout(state, `lab-${index}`) }));
  },

  addTerminal() {
    set((state) => {
      const { label, counters } = labelFor(state.paneCounters, "Terminal");
      return {
        paneCounters: counters,
        ...spawnContentPane(state, { kind: "terminal", owner: "local", label }),
      };
    });
  },

  addCapturedRun(provider) {
    // Each captured pane owns its own run: a fresh, stable per-pane key is both the
    // pane id and the key the pane spawns + persists its runId under (it rides on the
    // ref so the viewer reads it). Two Spawn Claude clicks are two independent runs
    // (two PTYs, isolated input), never a shared terminal. The incremental label
    // (Claude-1, Codex-2) rides on the ref so the chrome + dock show distinct names.
    const runKey = createCapturedRunKey(provider);
    set((state) => {
      const { label, counters } = labelFor(state.paneCounters, cliLabel(provider));
      return {
        paneCounters: counters,
        ...seedContentPane(state, runKey, {
          kind: "captured-run",
          owner: "local",
          provider,
          runKey,
          label,
        }),
      };
    });
  },

  restoreCapturedPane(paneId, provider) {
    // Reload re-attach: recreate the captured pane at its persisted key so the pane
    // re-attaches to its own run by id. Idempotent — a remount within a session finds
    // the pane already open and leaves it untouched.
    if (get().contentRefs[paneId]) return;
    set((state) =>
      seedContentPane(state, paneId, {
        kind: "captured-run",
        owner: "local",
        provider,
        runKey: paneId,
      }),
    );
  },

  minimizePane(paneId) {
    // Minimize ([-]): park the pane in the dock and remove it. Generic across kinds — the resolved
    // onMinimize hook runs inside the close window (captured-run has none: its run keeps running and
    // the binding is kept, so restore re-attaches by id). The non-destructive counterpart to close.
    dismissPane(paneId, "minimize");
  },

  closePane(paneId) {
    // Close ([X]): remove the pane and run its onClose hook — destructive and terminal. The
    // captured-run hook kills the run (DELETE); panes with no hook are a plain remove.
    dismissPane(paneId, "close");
  },

  restorePane(paneId) {
    // Re-seed a docked pane at its original id so its viewer re-mounts: a captured ref's ensureRun
    // resolves the kept run id (re-attach + PTY replay), a terminal opens a fresh PTY, a null ref
    // re-creates the demo card/ruler node from the id alone. A failed captured re-attach surfaces in
    // the viewer; the dock entry is already cleared here, so we never seek a replacement.
    set((state) => {
      const entry = state.docked.find((docked) => docked.paneId === paneId);
      if (!entry) return {};
      return {
        docked: state.docked.filter((docked) => docked.paneId !== paneId),
        contentRefs: entry.ref ? { ...state.contentRefs, [paneId]: entry.ref } : state.contentRefs,
        layout: seedPaneLayout(state, paneId),
      };
    });
  },

  closeDockedPane(paneId) {
    // Close/kill a docked pane in place — no restore. It is already off the canvas, so there is no
    // node teardown: just run its onClose hook (captured-run -> stopRun, DELETE; plain panes have
    // none, same seam as an on-canvas close) and drop the dock entry.
    const entry = get().docked.find((docked) => docked.paneId === paneId);
    if (!entry) return;
    if (entry.ref) resolvePaneLifecycle(entry.ref).onClose?.(entry.ref);
    set((state) => ({ docked: state.docked.filter((docked) => docked.paneId !== paneId) }));
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

// Minimize parks the pane in the dock for local restore; close discards it. The per-kind resource
// side effect (e.g. captured-run kill on close) is resolved through the lifecycle policy, not here.
type PaneDismissMode = "minimize" | "close";

// Node + camera teardown shared by minimize and close. Remove the node, re-plan so survivors flow
// into the gap, and reflow the camera (collapse expand, leave a frame, or undo a manual zoom-in)
// exactly as before. Returns the layout/expanded/framing patch and triggers the fly side effects
// itself. A fitted close is reserved for those three cases; normal overview / zoomed-out closes keep
// the camera. Mirrors the production canvasStore close protocol.
function finalizePaneRemoval(
  state: CanvasLabState,
  paneId: PaneId,
): Pick<CanvasLabState, "expandedPaneId" | "framing" | "layout"> {
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
  return { expandedPaneId, framing, layout };
}

// Shared two-phase teardown for both minimize and close. The exit animation and reflow are identical
// across kinds and modes; only the lifecycle hook (and whether the pane docks) differs. Mark the pane
// closing (it fades + scales out in place, neighbours hold their slots), then after the exit window
// run the resolved hook (close -> captured-run stopRun; minimize -> none today), dock it on minimize,
// drop the node, and reflow survivors into the gap.
function dismissPane(paneId: PaneId, mode: PaneDismissMode): void {
  useCanvasLabStore.setState((state) => ({ layout: markNodeClosing(state.layout, paneId) }));
  window.setTimeout(() => {
    const state = useCanvasLabStore.getState();
    const closingRef = state.contentRefs[paneId] ?? null;
    if (closingRef) {
      const policy = resolvePaneLifecycle(closingRef);
      if (mode === "close") policy.onClose?.(closingRef);
      else policy.onMinimize?.(closingRef);
    }
    const removal = finalizePaneRemoval(state, paneId);
    const { [paneId]: _closed, ...contentRefs } = state.contentRefs;
    // Minimize parks the pane in the dock (most-recent first) for local restore; close discards it.
    const docked: DockedPane[] =
      mode === "minimize" ? [{ paneId, ref: closingRef }, ...state.docked] : state.docked;
    useCanvasLabStore.setState({ ...removal, contentRefs, docked });
  }, CLOSE_DELAY_MS);
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
    docked: [],
    paneCounters: {},
  });
}
