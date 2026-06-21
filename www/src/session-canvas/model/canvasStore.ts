import { create } from "zustand";
import { persist } from "zustand/middleware";
import {
  type CanvasViewport,
  createInitialEngineLayoutState,
  focusNode,
  movePaneOrder,
  type PaneId,
  removeNode,
  setViewport as setEngineViewport,
  updateNodeRect,
  type ViewportBounds,
  type WorldRect,
} from "../../engine";
import { type LayoutParams, seedParams } from "../../engine/layout";
import type { HarnessName } from "../../types";
import { canvasCacheKey, importLegacyCanvasCache } from "../persistence/canvasCacheStorage";
import { type CanvasLaunchContext, defaultCanvasId } from "../route";
import { PICKER_PANE_ID, paneIdForRef, titleForRef } from "../viewers/registry";
import { createCanvasStorePersistOptions } from "./canvasStore.persistence";
import { planExpandLayout } from "./expandLayout";
import { DEFAULT_BOUNDS, INITIAL_STRATEGY_ID } from "./layoutPlanning";
import {
  dismissPane,
  emptyFraming,
  type FramingState,
  invokeDockedPaneCloseLifecycle,
  invokeDockedPaneRestoreLifecycle,
  type PaneDismissalPlan,
  type PaneDismissMode,
  parkDockedPane,
  planAffordanceLayout,
  planPaneExpand,
  planPaneFrame,
  planPaneUnexpand,
  planPaneUnframe,
  planSpawnedAffordancePaneLayout,
  removeDockedPane,
  runDockPaneFlow,
  runSpawnPaneFlow,
  stripPaneFlyIntent,
} from "./paneAffordances";
import {
  type CanvasModel,
  type CanvasPaneRef,
  type DockedPane,
  harnessLabel,
  type PaneContentRef,
  type PaneRecord,
  type SpawnablePaneRef,
  type SpawnSessionDescriptor,
} from "./paneRecords";
import { createCapturedRunRef, createPaneRecord, normalizeRef, titleForSession } from "./spawn";

interface CanvasStoreModel extends CanvasModel {
  activeStrategyId: string;
  bounds: ViewportBounds;
  fitToContent: boolean;
  params: LayoutParams;
  framing: FramingState;
  expandedPaneId: PaneId | null;
  docked: DockedPane[];
}

interface CanvasStoreState extends CanvasStoreModel {
  addCapturedRun(provider: HarnessName, runtimeTemplate?: string): PaneId;
  closePane(paneId: PaneId): void;
  closeDockedPane(paneId: PaneId): void;
  dropCapturedRunPane(runKey: string): void;
  expandPane(paneId: PaneId): void;
  focusPane(paneId: PaneId): void;
  framePane(paneId: PaneId): void;
  initializeCanvas(launch: CanvasLaunchContext): void;
  minimizePane(paneId: PaneId): void;
  movePane(paneId: PaneId, rect: WorldRect): void;
  // Terminal delivery parks a resource straight into the dock: no pane is
  // opened, the layout never replans. An already-open pane minimizes instead.
  dockPane(ref: SpawnablePaneRef): PaneId;
  commitReorder(paneId: PaneId, index: number): void;
  resizePane(paneId: PaneId, rect: WorldRect): void;
  resetViewport(): void;
  restorePane(paneId: PaneId): void;
  // Dock drag-out (doc 18): restore at the order slot the drop point chose.
  restorePaneAtIndex(paneId: PaneId, index: number): void;
  setBounds(bounds: ViewportBounds): void;
  setViewport(viewport: CanvasViewport): void;
  spawnPane(ref: SpawnablePaneRef, options?: SpawnPaneOptions): PaneId;
  spawnOrFocusTranscript(session: SpawnSessionDescriptor): void;
  unexpand(): void;
  unframe(): void;
}

interface SpawnPaneOptions {
  focus?: boolean;
  title?: string;
}

const INITIAL_LAUNCH_CONTEXT: CanvasLaunchContext = Object.freeze({
  owner: "local",
  workspaceHash: null,
  spaceId: null,
  worktreeId: null,
  canvasId: null,
  harness: null,
  runId: null,
});

// Mirrors the live store's canvasId for the persist storage's per-canvas
// namespacing, kept in sync wherever the canvas is (re)keyed. A module variable
// avoids a circular type reference to `useCanvasStore` inside its own persist
// options (which would collapse the store's inferred type to `any`).
let activeCanvasId = defaultCanvasId(INITIAL_LAUNCH_CONTEXT);

export const useCanvasStore = create<CanvasStoreState>()(
  persist(
    (set, get) => ({
      ...createInitialCanvasModel(INITIAL_LAUNCH_CONTEXT),

      addCapturedRun(provider, runtimeTemplate) {
        const worktreeId = get().defaultWorktreeId;
        if (worktreeId === null) {
          throw new Error("Cannot spawn a captured run without a rooted worktree");
        }
        const ref = createCapturedRunRef(
          provider,
          worktreeId,
          harnessLabel(provider),
          runtimeTemplate,
        );
        return get().spawnPane(ref, { focus: true });
      },

      closePane(paneId) {
        if (paneId === PICKER_PANE_ID) return;
        dismissPane(useCanvasStore, {
          paneId,
          mode: "close",
          getRef: canvasPaneRef,
          applyRemoval: applyCanvasPaneRemoval,
          planExpandedLayout: planExpandLayout,
        });
      },

      closeDockedPane(paneId) {
        const entry = get().docked.find((docked) => docked.paneId === paneId);
        if (!entry || entry.closeDisabled) return;
        invokeDockedPaneCloseLifecycle(entry);
        set((state) => ({ ...state, docked: removeDockedPane(state.docked, paneId) }));
      },

      dropCapturedRunPane(runKey) {
        set((state) => {
          const openPaneIds = Object.values(state.panes)
            .filter((pane) => isCapturedRunRef(pane.contentRef, runKey))
            .map((pane) => pane.paneId);
          const docked = state.docked.filter(
            (entry) =>
              !isCapturedRunRef(entry.ref, runKey) &&
              !isCapturedRunRef(entry.record?.contentRef, runKey),
          );
          if (openPaneIds.length === 0 && docked.length === state.docked.length) return {};

          let layout = state.layout;
          const panes = { ...state.panes };
          for (const paneId of openPaneIds) {
            layout = removeNode(layout, paneId);
            delete panes[paneId];
          }
          const expandedPaneId =
            state.expandedPaneId !== null && openPaneIds.includes(state.expandedPaneId)
              ? null
              : state.expandedPaneId;
          const framing =
            state.framing.paneId !== null && openPaneIds.includes(state.framing.paneId)
              ? emptyFraming()
              : state.framing;
          const nextState = { ...state, docked, expandedPaneId, framing, layout, panes };
          return {
            ...nextState,
            layout: planCanvasLayout(nextState),
          };
        });
      },

      expandPane(paneId) {
        const transition = planPaneExpand(get(), paneId, planExpandLayout);
        if (!transition) return;
        set(stripPaneFlyIntent(transition));
      },

      focusPane(paneId) {
        if (!get().panes[paneId] && get().docked.some((entry) => entry.paneId === paneId)) {
          get().restorePane(paneId);
          return;
        }
        set((state) => focusCanvasPane(state, paneId));
      },

      framePane(paneId) {
        const transition = planPaneFrame(get(), paneId);
        if (!transition) return;
        set(stripPaneFlyIntent(transition));
      },

      initializeCanvas(launch) {
        const canvasId = defaultCanvasId(launch);
        activeCanvasId = canvasId;
        // One-time: fold the pre-Spaces single canvas into this Space's default
        // Canvas. Runs BEFORE the canvasId set so the no-overwrite guard correctly
        // skips a Space that already has its own cached canvas.
        importLegacyCanvasCache(canvasId, globalThis.localStorage);
        // Capture the per-canvas blob (legacy-imported or pre-existing) before the
        // canvasId set: the persist middleware writes the current store state to the
        // new namespaced key on that set, which would otherwise clobber the cache we
        // are about to rehydrate from. Restore it, then rehydrate (mirrors reload).
        const cacheKey = canvasCacheKey(canvasId);
        const cached = globalThis.localStorage.getItem(cacheKey);
        set((state) => ({
          ...state,
          canvasId,
          spaceId: launch.spaceId,
          defaultWorktreeId: launch.worktreeId,
          launch,
          workspaceHash: launch.workspaceHash,
        }));
        if (cached !== null) globalThis.localStorage.setItem(cacheKey, cached);
        // canvasId changed → re-read the namespaced cache for the new canvas.
        void useCanvasStore.persist.rehydrate();
      },

      movePane(paneId, rect) {
        set((state) => ({ ...state, layout: updateNodeRect(state.layout, paneId, rect) }));
      },

      commitReorder(paneId, index) {
        set((state) => {
          const ordered = movePaneOrder(state.layout, paneId, index);
          return { layout: planCanvasLayout({ ...state, layout: ordered }) };
        });
      },

      minimizePane(paneId) {
        if (!get().panes[paneId]) return;
        dismissPane(useCanvasStore, {
          paneId,
          mode: "minimize",
          getRef: canvasPaneRef,
          applyRemoval: applyCanvasPaneRemoval,
          planExpandedLayout: planExpandLayout,
        });
      },

      resizePane(paneId, rect) {
        set((state) => ({ ...state, layout: updateNodeRect(state.layout, paneId, rect) }));
      },

      resetViewport() {
        set((state) => ({
          ...state,
          expandedPaneId: null,
          framing: emptyFraming(),
          layout: setEngineViewport(
            planCanvasLayout({ ...state, expandedPaneId: null, framing: emptyFraming() }),
            { panX: 0, panY: 0, scale: 1 },
          ),
        }));
      },

      restorePane(paneId) {
        // Restore in place = restore at the tail, where the seed appends anyway.
        get().restorePaneAtIndex(paneId, get().layout.order.length);
      },

      restorePaneAtIndex(paneId, index) {
        const entry = get().docked.find((docked) => docked.paneId === paneId);
        if (!entry?.record) return;
        const record = entry.record;
        invokeDockedPaneRestoreLifecycle(entry);
        set((state) => {
          const now = new Date().toISOString();
          const pane: PaneRecord = { ...record, lastFocusedAt: now };
          return {
            ...state,
            docked: removeDockedPane(state.docked, paneId),
            panes: { ...state.panes, [paneId]: pane },
            // Seed, splice to the drop index, and plan in one set: a single
            // replan, so the pane never flashes at the tail before its slot.
            layout: planSpawnedAffordancePaneLayout(state, paneId, planExpandLayout, true, index),
          };
        });
      },

      setViewport(viewport) {
        set((state) => ({ ...state, layout: setEngineViewport(state.layout, viewport) }));
      },

      setBounds(bounds) {
        set((state) => ({
          ...state,
          bounds,
          layout: planCanvasLayout({ ...state, bounds }),
        }));
      },

      dockPane(ref) {
        const normalized = normalizeRef(ref);
        const pane = createPaneRecord(
          normalized,
          titleForRef(normalized),
          new Date().toISOString(),
        );
        return runDockPaneFlow(pane.paneId, {
          isOpen: (paneId) => get().panes[paneId] !== undefined,
          minimizePane: (paneId) => get().minimizePane(paneId),
          park: (paneId) =>
            set((state) => ({
              docked: parkDockedPane(state.docked, paneId, normalized, pane),
            })),
        });
      },

      spawnPane(ref, options) {
        const normalized = normalizeRef(ref);
        const focus = options?.focus !== false;
        return runSpawnPaneFlow(paneIdForRef(normalized), focus, {
          isOpen: (paneId) => get().panes[paneId] !== undefined,
          focusPane: (paneId) => get().focusPane(paneId),
          isDocked: (paneId) => get().docked.some((entry) => entry.paneId === paneId),
          restorePane: (paneId) => get().restorePane(paneId),
          seed: () => {
            const title = options?.title ?? titleForRef(normalized);
            set((state) => insertPane(state, normalized, title, focus));
          },
        });
      },

      spawnOrFocusTranscript(session) {
        const title = titleForSession(session);
        const ref: PaneContentRef = {
          kind: "session-timeline",
          owner: "local",
          sessionId: session.sessionId,
          title,
        };
        get().spawnPane(ref, { focus: true, title });
      },

      unexpand() {
        const transition = planPaneUnexpand(get(), planExpandLayout);
        if (!transition) return;
        set(stripPaneFlyIntent(transition));
      },

      unframe() {
        const transition = planPaneUnframe(get());
        if (!transition) return;
        set(stripPaneFlyIntent(transition));
      },
    }),
    // The persist options are the 2nd arg to persist(), outside the (set, get)
    // creator closure; the module-level activeCanvasId mirror gives the live
    // canvasId without a self-reference to the store being defined.
    createCanvasStorePersistOptions<CanvasStoreState>(() => activeCanvasId),
  ),
);

function createInitialCanvasModel(launch: CanvasLaunchContext): CanvasStoreModel {
  const layout = createInitialEngineLayoutState();
  const ref: CanvasPaneRef = { kind: "session-picker", owner: "local" };
  const pane = createPaneRecord(ref, "Session picker", new Date().toISOString());
  const activeStrategyId = INITIAL_STRATEGY_ID;
  const params = seedParams(activeStrategyId);
  const canvasId = defaultCanvasId(launch);
  activeCanvasId = canvasId;
  const model: CanvasStoreModel = {
    canvasId,
    owner: "local",
    spaceId: launch.spaceId,
    workspaceHash: launch.workspaceHash,
    defaultWorktreeId: launch.worktreeId,
    cwd: null,
    launch,
    layout,
    panes: { [pane.paneId]: pane },
    activeStrategyId,
    bounds: DEFAULT_BOUNDS,
    fitToContent: true,
    params,
    framing: emptyFraming(),
    expandedPaneId: null,
    docked: [],
  };
  return {
    ...model,
    layout: planSpawnedAffordancePaneLayout(model, pane.paneId, planExpandLayout),
  };
}

function insertPane(
  state: CanvasStoreState,
  ref: CanvasPaneRef,
  title: string,
  focus: boolean,
): Partial<CanvasStoreState> {
  const pane = createPaneRecord(ref, title, new Date().toISOString());
  const panes = { ...state.panes, [pane.paneId]: pane };
  return {
    panes,
    layout: planSpawnedAffordancePaneLayout(state, pane.paneId, planExpandLayout, focus),
  };
}

function planCanvasLayout(state: CanvasStoreState): CanvasStoreState["layout"] {
  return planAffordanceLayout(state, state.fitToContent, state.expandedPaneId, planExpandLayout);
}

function focusCanvasPane(state: CanvasStoreState, paneId: PaneId): Partial<CanvasStoreState> {
  const pane = state.panes[paneId];
  if (!pane) return state;
  const now = new Date().toISOString();
  const panes: Record<PaneId, PaneRecord> = {
    ...state.panes,
    [paneId]: { ...pane, lastFocusedAt: now },
  };
  return { panes, layout: focusNode(state.layout, paneId) };
}

function canvasPaneRef(state: CanvasStoreState, paneId: PaneId): CanvasPaneRef | null {
  return state.panes[paneId]?.contentRef ?? null;
}

function isCapturedRunRef(ref: CanvasPaneRef | null | undefined, runKey: string): boolean {
  return ref?.kind === "captured-run" && ref.runKey === runKey;
}

function applyCanvasPaneRemoval(
  state: CanvasStoreState,
  plan: PaneDismissalPlan,
  ref: CanvasPaneRef | null,
  mode: PaneDismissMode,
  paneId: PaneId,
): Partial<CanvasStoreState> {
  const pane = state.panes[paneId];
  const { [paneId]: _removed, ...panes } = state.panes;
  const docked =
    mode === "minimize" && pane
      ? parkDockedPane(state.docked, paneId, ref, pane, pane.paneId === PICKER_PANE_ID)
      : state.docked;
  return { ...stripPaneFlyIntent(plan), docked, panes };
}

export function resetCanvasStoreForTests(
  launch: CanvasLaunchContext = INITIAL_LAUNCH_CONTEXT,
): void {
  useCanvasStore.setState(createInitialCanvasModel(launch));
}
