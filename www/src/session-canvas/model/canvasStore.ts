import { create } from "zustand";
import { persist } from "zustand/middleware";
import {
  type CanvasViewport,
  createInitialEngineLayoutState,
  focusNode,
  movePaneOrder,
  type PaneId,
  setViewport as setEngineViewport,
  updateNodeRect,
  type ViewportBounds,
  type WorldRect,
} from "../../engine";
import { type LayoutParams, seedParams } from "../../engine/layout";
import type { CanvasLaunchContext } from "../route";
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
import type {
  CanvasModel,
  CanvasPaneRef,
  DockedPane,
  PaneContentRef,
  PaneRecord,
  SpawnablePaneRef,
  SpawnSessionDescriptor,
} from "./paneRecords";
import { createPaneRecord, normalizeRef, titleForSession } from "./spawn";

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
  closePane(paneId: PaneId): void;
  closeDockedPane(paneId: PaneId): void;
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
  cli: null,
  runId: null,
});

export const useCanvasStore = create<CanvasStoreState>()(
  persist(
    (set, get) => ({
      ...createInitialCanvasModel(INITIAL_LAUNCH_CONTEXT),

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
        set((state) => ({
          ...state,
          id: launch.workspaceHash ?? "direct-local",
          launch,
          workspaceHash: launch.workspaceHash,
        }));
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
          sessionId: session.session_id,
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
    createCanvasStorePersistOptions<CanvasStoreState>(),
  ),
);

function createInitialCanvasModel(launch: CanvasLaunchContext): CanvasStoreModel {
  const layout = createInitialEngineLayoutState();
  const ref: CanvasPaneRef = { kind: "session-picker", owner: "local" };
  const pane = createPaneRecord(ref, "Session picker", new Date().toISOString());
  const activeStrategyId = INITIAL_STRATEGY_ID;
  const params = seedParams(activeStrategyId);
  const model: CanvasStoreModel = {
    id: launch.workspaceHash ?? "direct-local",
    owner: "local",
    workspaceHash: launch.workspaceHash,
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
