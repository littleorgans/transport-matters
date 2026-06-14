import { normalizeLayoutOrder } from "../../engine";
import { FRONTEND_STORAGE_KEYS } from "../../stores/persistence";
import { isPaneContentRef, type PaneContentRef } from "../model/paneRecords";
import type { RebuiltCanvasState } from "../persistence/canvasPanePersistence";
import { createCanvasPersistOptions } from "../persistence/canvasPersistOptions";
import type { CanvasLabState } from "./canvasLabTypes";

export const CANVAS_LAB_STORAGE_VERSION = 2;

export const canvasLabPersistOptions = createCanvasPersistOptions<CanvasLabState, PaneContentRef>({
  name: FRONTEND_STORAGE_KEYS.canvasLabStore,
  version: CANVAS_LAB_STORAGE_VERSION,
  isContentRef: isPaneContentRef,
  getContentRefs: (state) => state.contentRefs,
  mergeCanvasState: mergeCanvasLabState,
  // Persist the core pane rebuild set plus lab scaffolding counters. Transient camera and animation
  // state is intentionally left out.
  partializeExtras: (state) => ({
    paneCounters: state.paneCounters,
    nextPaneIndex: state.nextPaneIndex,
    textShadow: state.textShadow,
  }),
  mergeExtras: (saved) => ({
    paneCounters: isPaneCounters(saved.paneCounters) ? saved.paneCounters : {},
    nextPaneIndex: typeof saved.nextPaneIndex === "number" ? saved.nextPaneIndex : 0,
    textShadow: saved.textShadow === true,
  }),
});

function mergeCanvasLabState(
  _current: CanvasLabState,
  canvas: RebuiltCanvasState<PaneContentRef>,
): Partial<CanvasLabState> {
  return {
    layout: normalizeLayoutOrder(canvas.layout, canvas.order),
    docked: canvas.docked,
    activeStrategyId: canvas.activeStrategyId,
    params: canvas.params,
    fitToContent: canvas.fitToContent,
    expandedPaneId: canvas.expandedPaneId,
    contentRefs: canvas.contentRefs,
  };
}

function isPaneCounters(value: unknown): value is Record<string, number> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  return Object.values(value).every((count) => typeof count === "number");
}
