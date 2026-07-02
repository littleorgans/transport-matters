import {
  createPaneNode,
  type EngineLayoutState,
  nextPaneZ,
  type PaneId,
  upsertNode,
  type WorldRect,
} from "../../engine";
import { type LayoutParams, type ParamValue, sanitizeParam, seedParams } from "../../engine/layout";
import { isRecord } from "../../lib/isRecord";
import {
  type CanvasPaneRef,
  type DockedPane,
  isPaneContentRef,
  type PaneContentRef,
} from "../model/paneRecords";

interface CanvasPanePersistenceOptions<TRef extends CanvasPaneRef> {
  isContentRef(value: unknown): value is TRef;
}

export interface PersistedCanvasPanes<TRef extends CanvasPaneRef = PaneContentRef> {
  contentRefs: Record<PaneId, TRef>;
  paneRects: Record<PaneId, WorldRect>;
  order?: PaneId[];
  docked: DockedPane[];
}

export interface PersistedCanvasView {
  activeStrategyId: string;
  params: LayoutParams;
  fitToContent: boolean;
  expandedPaneId: PaneId | null;
}

export interface PersistedCanvasState<TRef extends CanvasPaneRef = PaneContentRef>
  extends PersistedCanvasPanes<TRef>,
    PersistedCanvasView {}

interface SeedPaneState<TRef extends CanvasPaneRef = PaneContentRef> {
  contentRefs: Record<PaneId, TRef>;
  layout: EngineLayoutState;
  docked?: DockedPane[];
}

interface SeedCanvasState<TRef extends CanvasPaneRef = PaneContentRef>
  extends SeedPaneState<TRef>,
    PersistedCanvasView {}

export interface RebuiltCanvasPanes<TRef extends CanvasPaneRef = PaneContentRef> {
  contentRefs: Record<PaneId, TRef>;
  layout: EngineLayoutState;
  order?: PaneId[];
  docked: DockedPane[];
}

export type PersistedCanvasPaneStatus = "absent" | "reset" | "hydrated";

export interface RebuiltCanvasState<TRef extends CanvasPaneRef = PaneContentRef>
  extends RebuiltCanvasPanes<TRef>,
    PersistedCanvasView {
  paneStatus: PersistedCanvasPaneStatus;
}

// The single node+ref seed: place a pane node at `rect` carrying an optional content ref (null is a
// demo/placeholder pane). Spawn and reload both funnel through this primitive, so create and restore
// cannot drift. No planning or focus happens here: callers layer those concerns on top.
export function seedPaneFromRecord<TRef extends CanvasPaneRef = PaneContentRef>(
  state: SeedPaneState<TRef>,
  paneId: PaneId,
  ref: TRef | null,
  rect: WorldRect,
): Pick<SeedPaneState<TRef>, "contentRefs" | "layout"> {
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
export function rebuildPersistedPanes<TRef extends CanvasPaneRef = PaneContentRef>(
  persisted: unknown,
  current: SeedPaneState<TRef>,
  options?: CanvasPanePersistenceOptions<TRef>,
): RebuiltCanvasPanes<TRef> {
  const saved = readPersistedPanes(persisted, contentRefGuard(options));
  return rebuildPersistedPanesFromSaved(saved, current);
}

function rebuildPersistedPanesFromSaved<TRef extends CanvasPaneRef = PaneContentRef>(
  saved: PersistedCanvasPanes<TRef> | null | undefined,
  current: SeedPaneState<TRef>,
): RebuiltCanvasPanes<TRef> {
  if (saved === undefined) return currentPanes(current);
  if (saved === null) return resetPanes(current);

  let seeded: SeedPaneState<TRef> = {
    contentRefs: {},
    layout: { ...current.layout, focusedPaneId: null, nodes: {}, order: [] },
  };

  for (const [paneId, rect] of Object.entries(saved.paneRects)) {
    seeded = seedPaneFromRecord(seeded, paneId, saved.contentRefs[paneId] ?? null, rect);
  }

  return {
    contentRefs: seeded.contentRefs,
    layout: seeded.layout,
    order: saved.order,
    docked: saved.docked,
  };
}

function currentPanes<TRef extends CanvasPaneRef = PaneContentRef>(
  current: SeedPaneState<TRef>,
): RebuiltCanvasPanes<TRef> {
  return {
    contentRefs: current.contentRefs,
    layout: current.layout,
    docked: current.docked ?? [],
  };
}

function resetPanes<TRef extends CanvasPaneRef = PaneContentRef>(
  current: SeedPaneState<TRef>,
): RebuiltCanvasPanes<TRef> {
  return {
    contentRefs: {},
    layout: { ...current.layout, focusedPaneId: null, nodes: {}, order: [] },
    docked: [],
  };
}

function readPersistedPanes<TRef extends CanvasPaneRef = PaneContentRef>(
  persisted: unknown,
  isContentRef: (value: unknown) => value is TRef,
): PersistedCanvasPanes<TRef> | null | undefined {
  if (persisted === undefined || persisted === null) return undefined;
  if (!isRecord(persisted)) return null;
  if (!hasPersistedPanePayload(persisted)) return undefined;

  const contentRefs = readContentRefs(persisted.contentRefs, isContentRef);
  const paneRects = readPaneRects(persisted.paneRects);
  const order = readPaneOrder(persisted.order);
  const docked = readDockedPanes(persisted.docked, isContentRef);
  if (!contentRefs || !paneRects || !docked) return null;
  return {
    contentRefs,
    paneRects: dropOrphanedRects(persisted.contentRefs, contentRefs, paneRects),
    order,
    docked,
  };
}

// A rect whose paneId carried a contentRef that FAILED the guard is now orphaned
// (its content was dropped as invalid). Drop the rect too, so the invalid pane
// fully disappears instead of resurrecting as a contentless ghost node. Rects with
// no persisted contentRef entry at all (demo/placeholder panes) are preserved.
function dropOrphanedRects(
  rawContentRefs: unknown,
  validContentRefs: Record<PaneId, unknown>,
  paneRects: Record<PaneId, WorldRect>,
): Record<PaneId, WorldRect> {
  if (!isRecord(rawContentRefs)) return paneRects;
  const pruned: Record<PaneId, WorldRect> = {};
  for (const [paneId, rect] of Object.entries(paneRects)) {
    if (paneId in rawContentRefs && !(paneId in validContentRefs)) continue;
    pruned[paneId] = rect;
  }
  return pruned;
}

function hasPersistedPanePayload(value: Record<string, unknown>): boolean {
  return "contentRefs" in value || "paneRects" in value || "docked" in value;
}

function readContentRefs<TRef extends CanvasPaneRef = PaneContentRef>(
  value: unknown,
  isContentRef: (candidate: unknown) => candidate is TRef,
): Record<PaneId, TRef> | null {
  if (value === undefined) return {};
  if (!isRecord(value)) return null;
  const contentRefs: Record<PaneId, TRef> = {};
  for (const [paneId, ref] of Object.entries(value)) {
    // Drop only the invalid ref (e.g. a pre-Slice-6 captured-run ref lacking
    // worktreeId); keep every valid sibling so one malformed/legacy entry never
    // nulls the whole map and resets the canvas. The now-orphaned rect is pruned
    // by dropOrphanedRects so the dropped pane fully disappears (no ghost node).
    if (isContentRef(ref)) contentRefs[paneId] = ref;
  }
  return contentRefs;
}

function readPaneRects(value: unknown): Record<PaneId, WorldRect> | null {
  if (value === undefined) return {};
  if (!isRecord(value)) return null;
  const rects: Record<PaneId, WorldRect> = {};
  for (const [paneId, rect] of Object.entries(value)) {
    if (!isWorldRect(rect)) return null;
    rects[paneId] = rect;
  }
  return rects;
}

function readPaneOrder(value: unknown): PaneId[] | undefined {
  if (!Array.isArray(value)) return undefined;
  return value.filter((id): id is PaneId => typeof id === "string");
}

function readDockedPanes<TRef extends CanvasPaneRef = PaneContentRef>(
  value: unknown,
  isContentRef: (candidate: unknown) => candidate is TRef,
): DockedPane[] | null {
  if (value === undefined) return [];
  if (!Array.isArray(value)) return null;
  const docked: DockedPane[] = [];
  for (const entry of value) {
    // Drop only the invalid docked entry; keep every valid docked pane so one bad
    // entry never nulls the whole dock.
    if (isPersistedDockedPane(entry, isContentRef)) docked.push(entry);
  }
  return docked;
}

function isPersistedDockedPane<TRef extends CanvasPaneRef = PaneContentRef>(
  value: unknown,
  isContentRef: (candidate: unknown) => candidate is TRef,
): value is DockedPane & { ref: TRef | null } {
  if (!isRecord(value)) return false;
  return (
    typeof value.paneId === "string" &&
    (value.ref === null || isContentRef(value.ref)) &&
    (value.closeDisabled === undefined || typeof value.closeDisabled === "boolean")
  );
}

function isWorldRect(value: unknown): value is WorldRect {
  if (!isRecord(value)) return false;
  return (
    Number.isFinite(value.x) &&
    Number.isFinite(value.y) &&
    Number.isFinite(value.width) &&
    Number.isFinite(value.height)
  );
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
export function rebuildPersistedCanvasState<TRef extends CanvasPaneRef = PaneContentRef>(
  persisted: unknown,
  current: SeedCanvasState<TRef>,
  options?: CanvasPanePersistenceOptions<TRef>,
): RebuiltCanvasState<TRef> {
  const saved = isRecord(persisted) ? (persisted as Partial<PersistedCanvasState<TRef>>) : {};
  const paneOptions = contentRefGuard(options);
  const persistedPanes = readPersistedPanes(persisted, paneOptions);
  const panes = rebuildPersistedPanesFromSaved(persistedPanes, current);
  if (persistedPanes === undefined) {
    return {
      ...panes,
      activeStrategyId: current.activeStrategyId,
      params: current.params,
      fitToContent: current.fitToContent,
      expandedPaneId: current.expandedPaneId,
      paneStatus: "absent",
    };
  }
  if (persistedPanes === null) {
    return {
      ...panes,
      activeStrategyId: current.activeStrategyId,
      params: current.params,
      fitToContent: current.fitToContent,
      expandedPaneId: null,
      paneStatus: "reset",
    };
  }
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
    paneStatus: "hydrated",
  };
}

function contentRefGuard<TRef extends CanvasPaneRef = PaneContentRef>(
  options: CanvasPanePersistenceOptions<TRef> | undefined,
): (value: unknown) => value is TRef {
  return options?.isContentRef ?? (isPaneContentRef as (value: unknown) => value is TRef);
}
