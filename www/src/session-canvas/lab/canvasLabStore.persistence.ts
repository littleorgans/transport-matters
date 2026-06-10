import type { PersistOptions } from "zustand/middleware";
import {
  createInitialEngineLayoutState,
  createPaneNode,
  type EngineLayoutState,
  nextPaneZ,
  type PaneId,
  upsertNode,
  type WorldRect,
} from "../../engine";
import { createFrontendPersistStorage, FRONTEND_STORAGE_KEYS } from "../../stores/persistence";
import type { DockedPane, PaneContentRef } from "../model/paneRecords";
import type { CanvasLabState } from "./canvasLabTypes";

export const CANVAS_LAB_STORAGE_VERSION = 1;

interface SeedPaneState {
  contentRefs: Record<PaneId, PaneContentRef>;
  layout: EngineLayoutState;
}

/** The persisted lab record set: enough to rebuild the canvas (open panes from contentRefs + paneRects,
 *  docked panes from `docked`) and continue the spawn counters, with no transient camera/animation state.
 *  Captured panes compose their live runId/minimized from capturedRunStore, keyed by the same runKey. */
export interface PersistedLabState {
  contentRefs: Record<PaneId, PaneContentRef>;
  paneRects: Record<PaneId, WorldRect>;
  docked: DockedPane[];
  paneCounters: Record<string, number>;
  nextPaneIndex: number;
}

// The single node+ref seed: place a pane node at `rect` carrying an optional content ref (null is a demo
// card/ruler stub). The one pane creation primitive both paths funnel through: spawn mints a fresh
// record, reload replays a persisted one, so create and restore cannot drift. No planning or focus here:
// spawn layers those on top; reload places each pane at its persisted rect.
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

// Rects of the open canvas panes only. Docked panes ride back in `docked`; a pane mid close animation
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
// docked records ride back in `docked`; captured panes re-attach by runId when their viewer mounts.
export function mergeLabState(persisted: unknown, current: CanvasLabState): CanvasLabState {
  const saved = (persisted ?? {}) as Partial<PersistedLabState>;
  const contentRefs = saved.contentRefs ?? {};
  const paneRects = saved.paneRects ?? {};
  let seeded: Pick<CanvasLabState, "contentRefs" | "layout"> = {
    contentRefs: {},
    layout: createInitialEngineLayoutState(),
  };
  for (const [paneId, rect] of Object.entries(paneRects)) {
    const next = seedPaneFromRecord(
      { ...current, ...seeded },
      paneId,
      contentRefs[paneId] ?? null,
      rect,
    );
    seeded = { contentRefs: next.contentRefs, layout: next.layout };
  }
  return {
    ...current,
    contentRefs: seeded.contentRefs,
    layout: seeded.layout,
    docked: saved.docked ?? [],
    paneCounters: saved.paneCounters ?? {},
    nextPaneIndex: saved.nextPaneIndex ?? 0,
  };
}

export const canvasLabPersistOptions: PersistOptions<CanvasLabState, PersistedLabState> = {
  name: FRONTEND_STORAGE_KEYS.canvasLabStore,
  storage: createFrontendPersistStorage<PersistedLabState>(),
  version: CANVAS_LAB_STORAGE_VERSION,
  // Persist only what rebuilds the canvas and continues the counters: the open record set, the docked
  // set, and the spawn counters. Transient camera and animation state is intentionally left out.
  partialize: (state): PersistedLabState => ({
    contentRefs: state.contentRefs,
    paneRects: collectOpenPaneRects(state.layout),
    docked: state.docked,
    paneCounters: state.paneCounters,
    nextPaneIndex: state.nextPaneIndex,
  }),
  merge: (persisted, current) => mergeLabState(persisted, current),
  // v1 is the first persisted shape; mergeLabState is shape tolerant, so migrate hands through.
  migrate: (persisted) => (persisted ?? {}) as PersistedLabState,
};
