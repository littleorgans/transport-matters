import {
  createPaneNode,
  type EngineLayoutState,
  nextPaneZ,
  type PaneId,
  upsertNode,
  type WorldRect,
} from "../../engine";
import type { DockedPane, PaneContentRef } from "../model/paneRecords";

export interface PersistedCanvasPanes {
  contentRefs: Record<PaneId, PaneContentRef>;
  paneRects: Record<PaneId, WorldRect>;
  docked: DockedPane[];
}

interface SeedPaneState {
  contentRefs: Record<PaneId, PaneContentRef>;
  layout: EngineLayoutState;
}

export interface RebuiltCanvasPanes {
  contentRefs: Record<PaneId, PaneContentRef>;
  layout: EngineLayoutState;
  docked: DockedPane[];
}

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
