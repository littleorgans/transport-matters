import { create } from "zustand";
import {
  type CanvasViewport,
  createInitialEngineLayoutState,
  focusNode,
  type PaneId,
  setViewport as setEngineViewport,
  updateNodeRect,
  type ViewportBounds,
  type WorldRect,
} from "../../engine";
import { type LayoutParams, seedParams } from "../../engine/layout";
import type { CanvasLaunchContext } from "../route";
import { PICKER_PANE_ID, paneIdForRef, titleForRef } from "../viewers/registry";
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
  resizePane(paneId: PaneId, rect: WorldRect): void;
  resetViewport(): void;
  restorePane(paneId: PaneId): void;
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

export const useCanvasStore = create<CanvasStoreState>()((set, get) => ({
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
        layout: planSpawnedAffordancePaneLayout(state, paneId, planExpandLayout),
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

  spawnPane(ref, options) {
    const normalized = normalizeRef(ref);
    const paneId = paneIdForRef(normalized);
    const existing = get().panes[paneId];
    if (existing) {
      if (options?.focus !== false) get().focusPane(paneId);
      return paneId;
    }
    const docked = get().docked.find((entry) => entry.paneId === paneId);
    if (docked) {
      get().restorePane(paneId);
      return paneId;
    }
    const title = options?.title ?? titleForRef(normalized);
    set((state) => insertPane(state, normalized, title, options?.focus !== false));
    return paneId;
  },

  spawnOrFocusTranscript(session) {
    const ref: PaneContentRef = {
      kind: "session-timeline",
      owner: "local",
      sessionId: session.session_id,
    };
    get().spawnPane(ref, { focus: true, title: titleForSession(session) });
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
}));

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
