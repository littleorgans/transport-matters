import type { PersistOptions } from "zustand/middleware";
import { createFrontendPersistStorage, FRONTEND_STORAGE_KEYS } from "../../stores/persistence";
import {
  collectOpenPaneRects,
  type PersistedCanvasPanes,
  rebuildPersistedPanes,
} from "../persistence/canvasPanePersistence";
import type { CanvasLabState } from "./canvasLabTypes";

export const CANVAS_LAB_STORAGE_VERSION = 1;

interface CanvasLabPersistedState extends PersistedCanvasPanes {
  paneCounters: Record<string, number>;
  nextPaneIndex: number;
}

function mergePersistedCanvasLabState(persisted: unknown, current: CanvasLabState): CanvasLabState {
  const saved = (persisted ?? {}) as Partial<CanvasLabPersistedState>;
  const panes = rebuildPersistedPanes(saved, current);

  return {
    ...current,
    ...panes,
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
    paneCounters: state.paneCounters,
    nextPaneIndex: state.nextPaneIndex,
  }),
  merge: (persisted, current) => mergePersistedCanvasLabState(persisted, current),
};
