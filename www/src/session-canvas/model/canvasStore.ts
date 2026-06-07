import { create } from "zustand";
import {
  type CanvasViewport,
  CLOSE_DELAY_MS,
  createInitialEngineLayoutState,
  createPaneNode,
  focusNode,
  markNodeClosing,
  nextPaneZ,
  type PaneId,
  removeNode,
  setViewport as setEngineViewport,
  updateNodeRect,
  upsertNode,
  type WorldRect,
} from "../../engine";
import type { CanvasLaunchContext } from "../route";
import type {
  CanvasModel,
  PaneContentRef,
  PaneRecord,
  SpawnSessionDescriptor,
} from "./paneRecords";
import {
  createPaneRecord,
  PICKER_PANE_ID,
  paneIdForRef,
  rectForRef,
  titleForSession,
} from "./spawn";

interface CanvasStoreState extends CanvasModel {
  closePane(paneId: PaneId): void;
  focusPane(paneId: PaneId): void;
  initializeCanvas(launch: CanvasLaunchContext): void;
  movePane(paneId: PaneId, rect: WorldRect): void;
  resizePane(paneId: PaneId, rect: WorldRect): void;
  resetViewport(): void;
  setViewport(viewport: CanvasViewport): void;
  spawnPane(ref: PaneContentRef, options?: SpawnPaneOptions): PaneId;
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
        return { ...state, panes, layout: removeNode(state.layout, paneId) };
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

  spawnPane(ref, options) {
    const paneId = paneIdForRef(ref);
    const existing = get().panes[paneId];
    if (existing) {
      if (options?.focus !== false) get().focusPane(paneId);
      return paneId;
    }
    const title =
      options?.title ?? (ref.kind === "session-picker" ? "Session picker" : "Transcript");
    set((state) => insertPane(state, ref, title, options?.focus !== false));
    return paneId;
  },

  spawnOrFocusTranscript(session) {
    const ref: PaneContentRef = { kind: "session", owner: "local", sessionId: session.session_id };
    get().spawnPane(ref, { focus: true, title: titleForSession(session) });
  },
}));

function createInitialCanvasModel(launch: CanvasLaunchContext): CanvasModel {
  const layout = createInitialEngineLayoutState();
  const ref: PaneContentRef = { kind: "session-picker", owner: "local" };
  const pane = createPaneRecord(ref, "Session picker", new Date().toISOString());
  const node = createPaneNode(pane.paneId, rectForRef(ref, 0), nextPaneZ(layout.nodes));
  const nextLayout = focusNode(upsertNode(layout, node), pane.paneId);
  return {
    id: launch.workspaceHash ?? "direct-local",
    owner: "local",
    workspaceHash: launch.workspaceHash,
    cwd: null,
    launch,
    layout: nextLayout,
    panes: { [pane.paneId]: pane },
  };
}

function insertPane(
  state: CanvasStoreState,
  ref: PaneContentRef,
  title: string,
  focus: boolean,
): Partial<CanvasStoreState> {
  const pane = createPaneRecord(ref, title, new Date().toISOString());
  const node = createPaneNode(
    pane.paneId,
    rectForRef(ref, Object.keys(state.panes).length),
    nextPaneZ(state.layout.nodes),
  );
  const layout = upsertNode(state.layout, node);
  const focusedLayout = focus ? focusNode(layout, pane.paneId) : layout;
  return {
    panes: { ...state.panes, [pane.paneId]: pane },
    layout: focusedLayout,
  };
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
