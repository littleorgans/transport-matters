import { normalizeLayoutOrder, type PaneId } from "../../engine";
import { FRONTEND_STORAGE_KEYS } from "../../stores/persistence";
import { createCanvasCacheStorage } from "../persistence/canvasCacheStorage";
import type { RebuiltCanvasState } from "../persistence/canvasPanePersistence";
import {
  createCanvasPersistOptions,
  type PersistableCanvasState,
} from "../persistence/canvasPersistOptions";
import { titleForRef } from "../viewers/registry";
import { type CanvasPaneRef, isCanvasPaneRef, type PaneRecord } from "./paneRecords";
import { createPaneRecord } from "./spawn";

export const CANVAS_STORE_STORAGE_VERSION = 1;

interface CanvasStorePersistableState extends PersistableCanvasState {
  panes: Record<PaneId, PaneRecord>;
}

export function createCanvasStorePersistOptions<State extends CanvasStorePersistableState>(
  getCanvasId: () => string,
) {
  return createCanvasPersistOptions<State, CanvasPaneRef>({
    name: FRONTEND_STORAGE_KEYS.canvasStore,
    version: CANVAS_STORE_STORAGE_VERSION,
    storage: createCanvasCacheStorage<unknown>(getCanvasId) as ReturnType<
      typeof createCanvasPersistOptions<State, CanvasPaneRef>
    >["storage"],
    isContentRef: isCanvasPaneRef,
    getContentRefs: paneRefsForOpenRecords,
    mergeCanvasState: mergeCanvasStoreState,
  });
}

function paneRefsForOpenRecords(state: CanvasStorePersistableState): Record<PaneId, CanvasPaneRef> {
  const refs: Record<PaneId, CanvasPaneRef> = {};
  for (const [paneId, pane] of Object.entries(state.panes)) {
    if (state.layout.nodes[paneId]?.lifecycle === "open") refs[paneId] = pane.contentRef;
  }
  return refs;
}

function mergeCanvasStoreState<State extends CanvasStorePersistableState>(
  current: State,
  canvas: RebuiltCanvasState<CanvasPaneRef>,
): Partial<State> {
  return {
    layout: normalizeLayoutOrder(canvas.layout, canvas.order),
    docked: canvas.docked,
    activeStrategyId: canvas.activeStrategyId,
    params: canvas.params,
    fitToContent: canvas.fitToContent,
    expandedPaneId: canvas.expandedPaneId,
    panes: paneRecordsFromRefs(current.panes, canvas.contentRefs),
  } as Partial<State>;
}

function paneRecordsFromRefs(
  current: Record<PaneId, PaneRecord>,
  contentRefs: Record<PaneId, CanvasPaneRef>,
): Record<PaneId, PaneRecord> {
  const now = new Date().toISOString();
  const panes: Record<PaneId, PaneRecord> = {};
  for (const [paneId, ref] of Object.entries(contentRefs)) {
    panes[paneId] = current[paneId] ?? createPaneRecord(ref, titleForRef(ref), now);
  }
  return panes;
}
