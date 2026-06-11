import type { PersistOptions } from "zustand/middleware";
import { createFrontendPersistStorage, FRONTEND_STORAGE_KEYS } from "../../stores/persistence";
import {
  collectOpenPaneRects,
  type PersistedCanvasState,
  rebuildPersistedCanvasState,
} from "../persistence/canvasPanePersistence";
import type { CanvasLabState } from "./canvasLabTypes";

export const CANVAS_LAB_STORAGE_VERSION = 2;

interface CanvasLabPersistedState extends PersistedCanvasState {
  paneCounters: Record<string, number>;
  nextPaneIndex: number;
}

function mergePersistedCanvasLabState(persisted: unknown, current: CanvasLabState): CanvasLabState {
  const saved = (persisted ?? {}) as Partial<CanvasLabPersistedState>;
  const canvas = rebuildPersistedCanvasState(saved, current);

  return {
    ...current,
    ...canvas,
    paneCounters: saved.paneCounters ?? {},
    nextPaneIndex: saved.nextPaneIndex ?? 0,
  };
}

export const canvasLabPersistOptions: PersistOptions<CanvasLabState, CanvasLabPersistedState> = {
  name: FRONTEND_STORAGE_KEYS.canvasLabStore,
  storage: createFrontendPersistStorage<CanvasLabPersistedState>(),
  version: CANVAS_LAB_STORAGE_VERSION,
  // Persist the core pane rebuild set plus lab scaffolding counters. Transient camera and animation
  // state is intentionally left out.
  partialize: (state): CanvasLabPersistedState => ({
    contentRefs: state.contentRefs,
    paneRects: collectOpenPaneRects(state.layout),
    docked: state.docked,
    activeStrategyId: state.activeStrategyId,
    params: state.params,
    fitToContent: state.fitToContent,
    expandedPaneId: state.expandedPaneId,
    paneCounters: state.paneCounters,
    nextPaneIndex: state.nextPaneIndex,
  }),
  merge: (persisted, current) => mergePersistedCanvasLabState(persisted, current),
};
