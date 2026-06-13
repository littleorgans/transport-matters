import { create } from "zustand";
import { persist } from "zustand/middleware";
import {
  createInitialEngineLayoutState,
  focusNode,
  movePaneOrder,
  type PaneId,
  setViewport as setEngineViewport,
  updateNodeRect,
} from "../../engine";
import { sanitizeParam, seedParams } from "../../engine/layout";
import { createCapturedRunKey } from "../model/capturedRunStore";
import { planExpandLayout } from "../model/expandLayout";
import {
  dismissPane,
  emptyFraming,
  invokeDockedPaneCloseLifecycle,
  invokeDockedPaneRestoreLifecycle,
  type PaneDismissalPlan,
  type PaneDismissMode,
  type PaneFlyIntent,
  parkDockedPane,
  planPaneExpand,
  planPaneFrame,
  planPaneUnexpand,
  planPaneUnframe,
  removeDockedPane,
  runDockPaneFlow,
  runSpawnPaneFlow,
  stripPaneFlyIntent,
} from "../model/paneAffordances";
import { type CanvasPaneRef, cliLabel, type PaneContentRef } from "../model/paneRecords";
import { paneIdForRef } from "../viewers/registry";
import {
  DEFAULT_BOUNDS,
  INITIAL_STRATEGY_ID,
  planLayout,
  spawnPaneLayout,
} from "./canvasLabLayout";
import { canvasLabPersistOptions } from "./canvasLabStore.persistence";
import type { CanvasLabState } from "./canvasLabTypes";

const FRAME_MS = 320;
const INITIAL_DEMO_PANE_COUNT = 4;

export { framedPaneId, UNFRAME_FLY_PANE_LIMIT } from "../model/paneAffordances";

type CanvasLabValues = Pick<
  CanvasLabState,
  | "layout"
  | "bounds"
  | "activeStrategyId"
  | "params"
  | "fitToContent"
  | "textShadow"
  | "oscColorReplies"
  | "framing"
  | "expandedPaneId"
  | "flying"
  | "paneMotion"
  | "nextPaneIndex"
  | "contentRefs"
  | "docked"
  | "paneCounters"
>;

function createEmptyCanvasLabValues(): CanvasLabValues {
  return {
    layout: createInitialEngineLayoutState(),
    bounds: DEFAULT_BOUNDS,
    activeStrategyId: INITIAL_STRATEGY_ID,
    params: seedParams(INITIAL_STRATEGY_ID),
    fitToContent: true,
    textShadow: false,
    oscColorReplies: true,
    framing: emptyFraming(),
    expandedPaneId: null,
    flying: false,
    paneMotion: false,
    nextPaneIndex: 0,
    contentRefs: {},
    docked: [],
    paneCounters: {},
  };
}

function createInitialCanvasLabValues(): CanvasLabValues {
  let seeded = createEmptyCanvasLabValues();
  for (let index = 1; index <= INITIAL_DEMO_PANE_COUNT; index += 1) {
    seeded = {
      ...seeded,
      nextPaneIndex: index,
      ...spawnPaneLayout(seeded, `lab-${index}`, null),
    };
  }
  return seeded;
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

function labPaneRef(state: CanvasLabState, paneId: PaneId): CanvasPaneRef | null {
  return state.contentRefs[paneId] ?? null;
}

function labDockedRef(ref: CanvasPaneRef | null): PaneContentRef | null {
  return ref?.kind === "session-picker" ? null : (ref ?? null);
}

function applyLabPaneRemoval(
  state: CanvasLabState,
  plan: PaneDismissalPlan,
  ref: CanvasPaneRef | null,
  mode: PaneDismissMode,
  paneId: PaneId,
): Partial<CanvasLabState> {
  const { [paneId]: _closed, ...contentRefs } = state.contentRefs;
  const docked = mode === "minimize" ? parkDockedPane(state.docked, paneId, ref) : state.docked;
  return { ...stripPaneFlyIntent(plan), contentRefs, docked };
}

export const useCanvasLabStore = create<CanvasLabState>()(
  persist(
    (set, get) => ({
      ...createInitialCanvasLabValues(),

      addPane() {
        set((state) => {
          const index = state.nextPaneIndex + 1;
          return { nextPaneIndex: index, ...spawnPaneLayout(state, `lab-${index}`, null) };
        });
      },

      addTerminal() {
        set((state) => {
          const index = state.nextPaneIndex + 1;
          const { label, counters } = labelFor(state.paneCounters, "Terminal");
          return {
            nextPaneIndex: index,
            paneCounters: counters,
            ...spawnPaneLayout(state, `lab-${index}`, { kind: "terminal", owner: "local", label }),
          };
        });
      },

      addCapturedRun(provider) {
        // Each captured pane owns its own run: a fresh, stable per-pane key is both the
        // pane id and the key the pane spawns + persists its runId under (it rides on the
        // ref so the viewer reads it). Two Spawn Claude clicks are two independent runs
        // (two PTYs, isolated input), never a shared terminal. The incremental label
        // (Claude-1, Codex-2) rides on the ref so the chrome + dock show distinct names,
        // and persists with the record so a reload keeps the exact title (no fallback).
        const runKey = createCapturedRunKey(provider);
        set((state) => {
          const { label, counters } = labelFor(state.paneCounters, cliLabel(provider));
          return {
            paneCounters: counters,
            ...spawnPaneLayout(state, runKey, {
              kind: "captured-run",
              owner: "local",
              provider,
              runKey,
              label,
            }),
          };
        });
      },

      dockPane(ref) {
        return runDockPaneFlow(paneIdForRef(ref), {
          isOpen: (paneId) => get().contentRefs[paneId] !== undefined,
          minimizePane: (paneId) => get().minimizePane(paneId),
          park: (paneId) => set((state) => ({ docked: parkDockedPane(state.docked, paneId, ref) })),
        });
      },

      spawnPane(ref, options) {
        return runSpawnPaneFlow(paneIdForRef(ref), options?.focus !== false, {
          isOpen: (paneId) => get().contentRefs[paneId] !== undefined,
          focusPane: (paneId) => get().focusPane(paneId),
          isDocked: (paneId) => get().docked.some((entry) => entry.paneId === paneId),
          restorePane: (paneId) => get().restorePane(paneId),
          seed: (paneId) => set((state) => spawnPaneLayout(state, paneId, ref)),
        });
      },

      minimizePane(paneId) {
        // Minimize ([-]): park the pane in the dock and remove it. Generic across kinds, the resolved
        // onMinimize hook runs inside the close window (captured-run has none: its run keeps running and
        // the binding is kept, so restore re-attaches by id). The non-destructive counterpart to close.
        dismissPane(useCanvasLabStore, {
          paneId,
          mode: "minimize",
          getRef: labPaneRef,
          applyRemoval: applyLabPaneRemoval,
          onFly: startFlyForIntent,
          planExpandedLayout: planExpandLayout,
        });
      },

      closePane(paneId) {
        // Close ([X]): remove the pane and run its onClose hook, destructive and terminal. The
        // captured-run hook kills the run (DELETE); panes with no hook are a plain remove.
        dismissPane(useCanvasLabStore, {
          paneId,
          mode: "close",
          getRef: labPaneRef,
          applyRemoval: applyLabPaneRemoval,
          onFly: startFlyForIntent,
          planExpandedLayout: planExpandLayout,
        });
      },

      restorePane(paneId) {
        // Restore in place = restore at the tail, where the seed appends anyway.
        get().restorePaneAtIndex(paneId, get().layout.order.length);
      },

      restorePaneAtIndex(paneId, index) {
        // Re-seed a docked pane at its original id so its viewer re-mounts: a captured ref's ensureRun
        // resolves the kept run id (re-attach + PTY replay), a terminal opens a fresh PTY, a null ref
        // re-creates the demo card/ruler node from the id alone. A failed captured re-attach surfaces in
        // the viewer; the dock entry is already cleared here, so we never seek a replacement.
        const entry = get().docked.find((docked) => docked.paneId === paneId);
        if (!entry) return;
        const ref = labDockedRef(entry.ref);
        // Re-attach side effect through the seam (the inverse of minimize): a captured-run clears its
        // persisted `minimized` flag so a reload after restore reopens it as a pane, not docked. Plain
        // panes declare no onRestore. Mirrors closeDockedPane's dispatch, zero kind=== branches here.
        invokeDockedPaneRestoreLifecycle(entry);
        // Seed, splice to the index, and plan in one set: a single replan, so
        // the pane never flashes at the tail before sliding to its slot.
        set((state) => ({
          docked: removeDockedPane(state.docked, paneId),
          ...spawnPaneLayout(state, paneId, ref, index),
        }));
      },

      closeDockedPane(paneId) {
        // Close/kill a docked pane in place, no restore. It is already off the canvas, so there is no
        // node teardown: just run its onClose hook (captured-run -> stopRun, DELETE; plain panes have
        // none, same seam as an on-canvas close) and drop the dock entry.
        const entry = get().docked.find((docked) => docked.paneId === paneId);
        if (!entry) return;
        invokeDockedPaneCloseLifecycle(entry);
        set((state) => ({ docked: removeDockedPane(state.docked, paneId) }));
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

      setTextShadow(on) {
        set({ textShadow: on });
      },

      setOscColorReplies(on) {
        set({ oscColorReplies: on });
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

      commitReorder(paneId, index) {
        set((state) => ({ layout: movePaneOrder(state.layout, paneId, index) }));
        get().organize();
      },

      setBounds(bounds) {
        set({ bounds });
        get().organize();
      },

      expandPane(paneId) {
        const transition = planPaneExpand(get(), paneId, planExpandLayout);
        if (!transition) return;
        startFlyForIntent(transition.fly);
        set(stripPaneFlyIntent(transition));
      },

      unexpand() {
        const transition = planPaneUnexpand(get(), planExpandLayout);
        if (!transition) return;
        startFlyForIntent(transition.fly);
        set(stripPaneFlyIntent(transition));
      },

      framePane(paneId) {
        const transition = planPaneFrame(get(), paneId);
        if (!transition) return;
        startFlyForIntent(transition.fly);
        set(stripPaneFlyIntent(transition));
      },

      unframe() {
        const transition = planPaneUnframe(get());
        if (!transition) return;
        startFlyForIntent(transition.fly);
        set(stripPaneFlyIntent(transition));
      },

      resetView() {
        startFly();
        set((state) => {
          const framing = emptyFraming();
          const expandedPaneId = null;
          return {
            framing,
            expandedPaneId,
            layout: setEngineViewport(
              planLayout(
                state.layout,
                state.bounds,
                state.activeStrategyId,
                state.params,
                state.fitToContent,
                expandedPaneId,
              ),
              { panX: 0, panY: 0, scale: 1 },
            ),
          };
        });
      },

      setViewport(viewport) {
        set((state) => ({ layout: setEngineViewport(state.layout, viewport) }));
      },
    }),
    canvasLabPersistOptions,
  ),
);

let flyTimer: number | null = null;

interface FlyOptions {
  paneMotion?: boolean;
}

function startFlyForIntent(intent: PaneFlyIntent): void {
  if (intent === "none") return;
  startFly({ paneMotion: intent === "pane-motion" });
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
  useCanvasLabStore.setState(createEmptyCanvasLabValues());
}
