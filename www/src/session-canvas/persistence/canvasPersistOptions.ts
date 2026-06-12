import type { PersistOptions } from "zustand/middleware";
import type { EngineLayoutState, PaneId } from "../../engine";
import { type LayoutParams, seedParams } from "../../engine/layout";
import { createFrontendPersistStorage } from "../../stores/persistence";
import { INITIAL_STRATEGY_ID } from "../model/layoutPlanning";
import type { CanvasPaneRef, DockedPane } from "../model/paneRecords";
import {
  collectOpenPaneRects,
  type PersistedCanvasPaneStatus,
  type PersistedCanvasState,
  type RebuiltCanvasState,
  rebuildPersistedCanvasState,
} from "./canvasPanePersistence";

export interface PersistableCanvasState {
  layout: EngineLayoutState;
  docked: DockedPane[];
  activeStrategyId: string;
  params: LayoutParams;
  fitToContent: boolean;
  expandedPaneId: PaneId | null;
}

type PersistedCanvasExtras = Partial<Record<string, unknown>>;
type PersistedCanvasSnapshot<TRef extends CanvasPaneRef> = PersistedCanvasState<TRef>;

export interface CanvasPersistOptionsConfig<
  State extends PersistableCanvasState,
  TRef extends CanvasPaneRef,
> {
  name: string;
  version: number;
  isContentRef(value: unknown): value is TRef;
  getContentRefs(state: State): Record<PaneId, TRef>;
  mergeCanvasState(current: State, canvas: RebuiltCanvasState<TRef>): Partial<State>;
  partializeExtras?: (state: State) => PersistedCanvasExtras;
  mergeExtras?: (saved: PersistedCanvasExtras, current: State) => Partial<State>;
}

export function createCanvasPersistOptions<
  State extends PersistableCanvasState,
  TRef extends CanvasPaneRef,
>(
  config: CanvasPersistOptionsConfig<State, TRef>,
): PersistOptions<State, PersistedCanvasSnapshot<TRef>> {
  return {
    name: config.name,
    storage: createFrontendPersistStorage<PersistedCanvasSnapshot<TRef>>(),
    version: config.version,
    partialize: (state): PersistedCanvasSnapshot<TRef> => ({
      ...partializeCanvasState(state, config.getContentRefs),
      ...(config.partializeExtras?.(state) ?? {}),
    }),
    migrate: () => emptyPersistedCanvasState<TRef>(),
    merge: (persisted, current) => mergePersistedCanvasState(persisted, current, config),
  };
}

function partializeCanvasState<State extends PersistableCanvasState, TRef extends CanvasPaneRef>(
  state: State,
  getContentRefs: (state: State) => Record<PaneId, TRef>,
): PersistedCanvasState<TRef> {
  return {
    contentRefs: getContentRefs(state),
    paneRects: collectOpenPaneRects(state.layout),
    order: [...state.layout.order],
    docked: state.docked,
    activeStrategyId: state.activeStrategyId,
    params: state.params,
    fitToContent: state.fitToContent,
    expandedPaneId: state.expandedPaneId,
  };
}

function emptyPersistedCanvasState<TRef extends CanvasPaneRef>(): PersistedCanvasState<TRef> {
  return {
    contentRefs: {},
    paneRects: {},
    order: [],
    docked: [],
    activeStrategyId: INITIAL_STRATEGY_ID,
    params: seedParams(INITIAL_STRATEGY_ID),
    fitToContent: true,
    expandedPaneId: null,
  };
}

function mergePersistedCanvasState<
  State extends PersistableCanvasState,
  TRef extends CanvasPaneRef,
>(persisted: unknown, current: State, config: CanvasPersistOptionsConfig<State, TRef>): State {
  const seed = { ...current, contentRefs: config.getContentRefs(current) };
  const canvas = rebuildPersistedCanvasState(persisted, seed, {
    isContentRef: config.isContentRef,
  });
  const saved = isPersistedExtras(persisted) ? persisted : {};

  return {
    ...current,
    ...config.mergeCanvasState(current, canvas),
    ...mergePersistedExtras(canvas.paneStatus, saved, current, config.mergeExtras),
  };
}

function mergePersistedExtras<State extends PersistableCanvasState>(
  paneStatus: PersistedCanvasPaneStatus,
  saved: PersistedCanvasExtras,
  current: State,
  mergeExtras: ((saved: PersistedCanvasExtras, current: State) => Partial<State>) | undefined,
): Partial<State> {
  if (paneStatus === "absent") return {};
  return mergeExtras?.(paneStatus === "reset" ? {} : saved, current) ?? {};
}

function isPersistedExtras(value: unknown): value is PersistedCanvasExtras {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
