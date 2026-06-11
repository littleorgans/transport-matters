import { create } from "zustand";
import { persist } from "zustand/middleware";
import {
  createInitialEngineLayoutState,
  focusNode,
  frameRectViewport,
  type PaneId,
  setViewport as setEngineViewport,
  updateNodeRect,
} from "../../engine";
import { sanitizeParam, seedParams } from "../../engine/layout";
import { resolvePaneLifecycle } from "../model/paneLifecycle";
import { cliLabel } from "../model/paneRecords";
import {
  DEFAULT_BOUNDS,
  INITIAL_STRATEGY_ID,
  openPaneIds,
  planLayout,
  spawnPaneLayout,
  UNFRAME_FLY_PANE_LIMIT,
} from "./canvasLabLayout";
import { dismissPane } from "./canvasLabPaneLifecycle";
import { canvasLabPersistOptions } from "./canvasLabStore.persistence";
import type { CanvasLabState, FramingState } from "./canvasLabTypes";
import { createCapturedRunKey } from "./capturedRunStore";

const FRAME_MS = 320;
const INITIAL_DEMO_PANE_COUNT = 4;

export { UNFRAME_FLY_PANE_LIMIT } from "./canvasLabLayout";

export function framedPaneId(framing: FramingState): PaneId | null {
  return framing.paneId;
}

type CanvasLabValues = Pick<
  CanvasLabState,
  | "layout"
  | "bounds"
  | "activeStrategyId"
  | "params"
  | "fitToContent"
  | "framing"
  | "expandedPaneId"
  | "flying"
  | "paneMotion"
  | "nextPaneIndex"
  | "contentRefs"
  | "docked"
  | "paneCounters"
>;

function emptyFraming(): FramingState {
  return { paneId: null, overview: null };
}

function createEmptyCanvasLabValues(): CanvasLabValues {
  return {
    layout: createInitialEngineLayoutState(),
    bounds: DEFAULT_BOUNDS,
    activeStrategyId: INITIAL_STRATEGY_ID,
    params: seedParams(INITIAL_STRATEGY_ID),
    fitToContent: true,
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

      minimizePane(paneId) {
        // Minimize ([-]): park the pane in the dock and remove it. Generic across kinds — the resolved
        // onMinimize hook runs inside the close window (captured-run has none: its run keeps running and
        // the binding is kept, so restore re-attaches by id). The non-destructive counterpart to close.
        dismissPane(useCanvasLabStore, paneId, "minimize", startFly);
      },

      closePane(paneId) {
        // Close ([X]): remove the pane and run its onClose hook — destructive and terminal. The
        // captured-run hook kills the run (DELETE); panes with no hook are a plain remove.
        dismissPane(useCanvasLabStore, paneId, "close", startFly);
      },

      restorePane(paneId) {
        // Re-seed a docked pane at its original id so its viewer re-mounts: a captured ref's ensureRun
        // resolves the kept run id (re-attach + PTY replay), a terminal opens a fresh PTY, a null ref
        // re-creates the demo card/ruler node from the id alone. A failed captured re-attach surfaces in
        // the viewer; the dock entry is already cleared here, so we never seek a replacement.
        const entry = get().docked.find((docked) => docked.paneId === paneId);
        if (!entry) return;
        // Re-attach side effect through the seam (the inverse of minimize): a captured-run clears its
        // persisted `minimized` flag so a reload after restore reopens it as a pane, not docked. Plain
        // panes declare no onRestore. Mirrors closeDockedPane's dispatch — zero kind=== branches here.
        if (entry.ref) resolvePaneLifecycle(entry.ref).onRestore?.(entry.ref);
        set((state) => ({
          docked: state.docked.filter((docked) => docked.paneId !== paneId),
          ...spawnPaneLayout(state, paneId, entry.ref),
        }));
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
    }),
    canvasLabPersistOptions,
  ),
);

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
  useCanvasLabStore.setState(createEmptyCanvasLabValues());
}
