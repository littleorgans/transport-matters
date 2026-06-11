import { create } from "zustand";
import {
  type CanvasViewport,
  CLOSE_DELAY_MS,
  createInitialEngineLayoutState,
  focusNode,
  markNodeClosing,
  type PaneId,
  removeNode,
  setViewport as setEngineViewport,
  updateNodeRect,
  type ViewportBounds,
  type WorldRect,
} from "../../engine";
import { type LayoutParams, seedParams } from "../../engine/layout";
import type { CanvasLaunchContext } from "../route";
import { PICKER_PANE_ID, paneIdForRef, titleForRef } from "../viewers/registry";
import {
  DEFAULT_BOUNDS,
  INITIAL_STRATEGY_ID,
  planLayout,
  planSpawnedPaneLayout,
} from "./layoutPlanning";
import type {
  CanvasModel,
  CanvasPaneRef,
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
}

interface CanvasStoreState extends CanvasStoreModel {
  closePane(paneId: PaneId): void;
  focusPane(paneId: PaneId): void;
  initializeCanvas(launch: CanvasLaunchContext): void;
  movePane(paneId: PaneId, rect: WorldRect): void;
  resizePane(paneId: PaneId, rect: WorldRect): void;
  resetViewport(): void;
  setBounds(bounds: ViewportBounds): void;
  setViewport(viewport: CanvasViewport): void;
  spawnPane(ref: SpawnablePaneRef, options?: SpawnPaneOptions): PaneId;
  spawnOrFocusTranscript(session: SpawnSessionDescriptor): void;
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
    set((state) => ({ ...state, layout: markNodeClosing(state.layout, paneId) }));
    window.setTimeout(() => {
      set((state) => {
        const { [paneId]: _removed, ...panes } = state.panes;
        const layout = planCanvasLayout({
          ...state,
          panes,
          layout: removeNode(state.layout, paneId),
        });
        return { ...state, panes, layout };
      });
    }, CLOSE_DELAY_MS);
  },

  focusPane(paneId) {
    set((state) => focusCanvasPane(state, paneId));
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

  resizePane(paneId, rect) {
    set((state) => ({ ...state, layout: updateNodeRect(state.layout, paneId, rect) }));
  },

  resetViewport() {
    set((state) => ({
      ...state,
      layout: setEngineViewport(state.layout, { panX: 0, panY: 0, scale: 1 }),
    }));
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
  };
  return {
    ...model,
    layout: planSpawnedPaneLayout(model, pane.paneId),
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
    layout: planSpawnedPaneLayout(state, pane.paneId, null, undefined, focus),
  };
}

function planCanvasLayout(state: CanvasStoreState): CanvasStoreState["layout"] {
  return planLayout(
    state.layout,
    state.bounds,
    state.activeStrategyId,
    state.params,
    state.fitToContent,
  );
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

export function resetCanvasStoreForTests(
  launch: CanvasLaunchContext = INITIAL_LAUNCH_CONTEXT,
): void {
  useCanvasStore.setState(createInitialCanvasModel(launch));
}
