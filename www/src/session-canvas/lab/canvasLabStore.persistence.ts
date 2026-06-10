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
import type { CanvasLabState } from "./canvasLabStore";

// The single node+ref seed: place a pane node at `rect` carrying an optional content ref (null is a demo
// card/ruler stub). The ONE pane-creation primitive both paths funnel through — spawn mints a fresh
// record, reload replays a persisted one — so create and restore can never drift. No planning or focus
// here: spawn layers those on top (spawnPaneLayout); reload places each pane at its persisted rect.
export function seedPaneFromRecord(
  state: CanvasLabState,
  paneId: PaneId,
  ref: PaneContentRef | null,
  rect: WorldRect,
): Pick<CanvasLabState, "contentRefs" | "layout"> {
  return {
    contentRefs: ref ? { ...state.contentRefs, [paneId]: ref } : state.contentRefs,
    layout: upsertNode(state.layout, createPaneNode(paneId, rect, nextPaneZ(state.layout.nodes))),
  };
}

const CANVAS_LAB_STORAGE_VERSION = 1;

/** The persisted lab record set: enough to rebuild the canvas (open panes from contentRefs + paneRects,
 *  docked panes from `docked`) and continue the spawn counters, with no transient camera/animation state.
 *  Captured panes compose their live runId/minimized from capturedRunStore, keyed by the same runKey. */
interface PersistedLabState {
  contentRefs: Record<PaneId, PaneContentRef>;
  paneRects: Record<PaneId, WorldRect>;
  docked: DockedPane[];
  paneCounters: Record<string, number>;
  nextPaneIndex: number;
}

// Rects of the OPEN canvas panes only. Docked panes ride back in `docked`; a pane mid-close-animation
// (closing) must not resurrect on reload, so it is excluded too.
function collectOpenPaneRects(layout: EngineLayoutState): Record<PaneId, WorldRect> {
  const rects: Record<PaneId, WorldRect> = {};
  for (const node of Object.values(layout.nodes)) {
    if (node.lifecycle === "open") rects[node.paneId] = node.rect;
  }
  return rects;
}

// Reload hydration: rebuild the canvas from the persisted record set through the SAME seedPaneFromRecord
// primitive the spawn path uses, so create and restore can never diverge. Each open record seeds a node at
// its persisted rect carrying its persisted ref (label included → titles survive); docked records ride
// back in `docked`; captured panes re-attach by runId when their viewer mounts (capturedRunStore). Fully
// defensive against a missing/partial payload (the first load after upgrade has no lab-store key), so
// hydration never crashes or wipes the run bindings.
function mergeLabState(persisted: unknown, current: CanvasLabState): CanvasLabState {
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

// The zustand persist config for the lab store: what to persist (partialize), how to rebuild on reload
// (merge → mergeLabState), and the versioned shape-tolerant migrate. Lives beside the seed/hydrate
// primitives it drives so the store body stays thin and the record<->state seam is one module.
export const canvasLabPersistOptions: PersistOptions<CanvasLabState, PersistedLabState> = {
  name: FRONTEND_STORAGE_KEYS.canvasLabStore,
  storage: createFrontendPersistStorage<PersistedLabState>(),
  version: CANVAS_LAB_STORAGE_VERSION,
  // Persist only what rebuilds the canvas + continues the counters: the open record set (contentRefs
  // WITH label + per-pane rect), the docked set (every kind), and the spawn counters. Transient camera
  // and animation state is intentionally left out so a reload lands on a clean overview.
  partialize: (state): PersistedLabState => ({
    contentRefs: state.contentRefs,
    paneRects: collectOpenPaneRects(state.layout),
    docked: state.docked,
    paneCounters: state.paneCounters,
    nextPaneIndex: state.nextPaneIndex,
  }),
  merge: (persisted, current) => mergeLabState(persisted, current),
  // v1 is the first persisted shape; mergeLabState is fully shape-tolerant, so migrate just hands the
  // payload through and a future bump localizes any structural change here.
  migrate: (persisted) => (persisted ?? {}) as PersistedLabState,
};
