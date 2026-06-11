import {
  createPaneNode,
  type EngineLayoutState,
  nextPaneZ,
  type PaneId,
  upsertNode,
  type WorldRect,
} from "../../engine";
import { type LayoutParams, type ParamValue, sanitizeParam, seedParams } from "../../engine/layout";
import type { DockedPane, PaneContentRef } from "../model/paneRecords";

export interface PersistedCanvasPanes {
  contentRefs: Record<PaneId, PaneContentRef>;
  paneRects: Record<PaneId, WorldRect>;
  docked: DockedPane[];
}

export interface PersistedCanvasView {
  activeStrategyId: string;
  params: LayoutParams;
  fitToContent: boolean;
  expandedPaneId: PaneId | null;
}

export interface PersistedCanvasState extends PersistedCanvasPanes, PersistedCanvasView {}

interface SeedPaneState {
  contentRefs: Record<PaneId, PaneContentRef>;
  layout: EngineLayoutState;
}

interface SeedCanvasState extends SeedPaneState, PersistedCanvasView {}

export interface RebuiltCanvasPanes {
  contentRefs: Record<PaneId, PaneContentRef>;
  layout: EngineLayoutState;
  docked: DockedPane[];
}

export interface RebuiltCanvasState extends RebuiltCanvasPanes, PersistedCanvasView {}

// The single node+ref seed: place a pane node at `rect` carrying an optional content ref (null is a
// demo/placeholder pane). Spawn and reload both funnel through this primitive, so create and restore
// cannot drift. No planning or focus happens here: callers layer those concerns on top.
export function seedPaneFromRecord(
  state: SeedPaneState,
  paneId: PaneId,
  ref: PaneContentRef | null,
  rect: WorldRect,
): Pick<SeedPaneState, "contentRefs" | "layout"> {
  return {
    contentRefs: ref ? { ...state.contentRefs, [paneId]: ref } : state.contentRefs,
    layout: upsertNode(state.layout, createPaneNode(paneId, rect, nextPaneZ(state.layout.nodes))),
  };
}

// Rects of open canvas panes only. Docked panes ride back in `docked`; a pane mid close animation
// must not resurrect on reload, so it is excluded too.
export function collectOpenPaneRects(layout: EngineLayoutState): Record<PaneId, WorldRect> {
  const rects: Record<PaneId, WorldRect> = {};
  for (const node of Object.values(layout.nodes)) {
    if (node.lifecycle === "open") rects[node.paneId] = node.rect;
  }
  return rects;
}

// Reload hydration: rebuild the canvas from the persisted record set through the same seed primitive
// the spawn path uses. Each open record seeds a node at its persisted rect carrying its persisted ref;
// docked records ride back in `docked` for the surface adapter to expose.
export function rebuildPersistedPanes(
  persisted: unknown,
  current: SeedPaneState,
): RebuiltCanvasPanes {
  const saved = (persisted ?? {}) as Partial<PersistedCanvasPanes>;
  const contentRefs = saved.contentRefs ?? {};
  const paneRects = saved.paneRects ?? {};
  let seeded: SeedPaneState = {
    contentRefs: {},
    layout: { ...current.layout, focusedPaneId: null, nodes: {} },
  };

  for (const [paneId, rect] of Object.entries(paneRects)) {
    seeded = seedPaneFromRecord(seeded, paneId, contentRefs[paneId] ?? null, rect);
  }

  return {
    contentRefs: seeded.contentRefs,
    layout: seeded.layout,
    docked: saved.docked ?? [],
  };
}

function canResolveStrategy(strategyId: string): boolean {
  try {
    seedParams(strategyId);
    return true;
  } catch {
    return false;
  }
}

function isParamValue(value: unknown): value is ParamValue {
  return typeof value === "number" || typeof value === "boolean" || typeof value === "string";
}

function restoreActiveStrategyId(
  saved: Partial<PersistedCanvasView>,
  current: PersistedCanvasView,
): string {
  if (typeof saved.activeStrategyId !== "string") return current.activeStrategyId;
  return canResolveStrategy(saved.activeStrategyId)
    ? saved.activeStrategyId
    : current.activeStrategyId;
}

function restoreParams(strategyId: string, params: unknown): LayoutParams {
  const restored = seedParams(strategyId);
  if (params === null || typeof params !== "object" || Array.isArray(params)) return restored;

  for (const [key, value] of Object.entries(params)) {
    if (!isParamValue(value)) continue;
    const sanitized = sanitizeParam(strategyId, key, value);
    if (sanitized !== undefined) restored[key] = sanitized;
  }

  return restored;
}

function restoreExpandedPaneId(
  saved: Partial<PersistedCanvasView>,
  openPaneIds: PaneId[],
): PaneId | null {
  if (typeof saved.expandedPaneId !== "string") return null;
  return openPaneIds.length > 1 && openPaneIds.includes(saved.expandedPaneId)
    ? saved.expandedPaneId
    : null;
}

// Reload hydration for the full core canvas shape: panes rebuild from persisted rects, while the
// view controls hydrate without re-planning. The camera stays transient on `current.layout`.
export function rebuildPersistedCanvasState(
  persisted: unknown,
  current: SeedCanvasState,
): RebuiltCanvasState {
  const saved = (persisted ?? {}) as Partial<PersistedCanvasState>;
  const panes = rebuildPersistedPanes(saved, current);
  const openPaneIds = Object.values(panes.layout.nodes)
    .filter((node) => node.lifecycle === "open")
    .map((node) => node.paneId);
  const activeStrategyId = restoreActiveStrategyId(saved, current);

  return {
    ...panes,
    activeStrategyId,
    params: restoreParams(activeStrategyId, saved.params),
    fitToContent:
      typeof saved.fitToContent === "boolean" ? saved.fitToContent : current.fitToContent,
    expandedPaneId: restoreExpandedPaneId(saved, openPaneIds),
  };
}
