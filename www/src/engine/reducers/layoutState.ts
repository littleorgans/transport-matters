import type {
  CanvasViewport,
  EngineLayoutState,
  PaneId,
  PaneNode,
  ViewportBounds,
  WorldRect,
} from "../types";
import { clampScale } from "../viewport";

export const DEFAULT_CANVAS_VIEWPORT: CanvasViewport = Object.freeze({
  panX: 0,
  panY: 0,
  scale: 1,
});

const Z_STEP = 1;

// How long a pane stays mounted in the "closing" state before removeNode unmounts it. The exit
// animation (PaneFrame) is timed to this exact window so the pane finishes fading as it is removed.
export const CLOSE_DELAY_MS = 200;

export function createInitialEngineLayoutState(): EngineLayoutState {
  return {
    mode: "floating",
    viewport: DEFAULT_CANVAS_VIEWPORT,
    nodes: {},
    order: [],
    focusedPaneId: null,
  };
}

export function nextPaneZ(nodes: Record<PaneId, PaneNode>): number {
  const highest = Object.values(nodes).reduce((max, node) => Math.max(max, node.z), 0);
  return highest + Z_STEP;
}

export function upsertNode(state: EngineLayoutState, node: PaneNode): EngineLayoutState {
  return {
    ...state,
    nodes: { ...state.nodes, [node.paneId]: node },
    // Insert-or-replace: append to the order only when the id is new, or a
    // re-upsert would duplicate the entry and break order === nodes ids.
    order: state.order.includes(node.paneId) ? state.order : [...state.order, node.paneId],
  };
}

export function focusNode(state: EngineLayoutState, paneId: PaneId): EngineLayoutState {
  const node = state.nodes[paneId];
  if (!node) return state;
  return {
    ...state,
    focusedPaneId: paneId,
    nodes: {
      ...state.nodes,
      [paneId]: { ...node, z: nextPaneZ(state.nodes) },
    },
  };
}

export function updateNodeRect(
  state: EngineLayoutState,
  paneId: PaneId,
  rect: WorldRect,
): EngineLayoutState {
  const node = state.nodes[paneId];
  if (!node) return state;
  return {
    ...state,
    nodes: { ...state.nodes, [paneId]: { ...node, rect } },
  };
}

function rectsEqual(a: WorldRect, b: WorldRect): boolean {
  return a.x === b.x && a.y === b.y && a.width === b.width && a.height === b.height;
}

// Apply many planned rects in a single nodes copy. updateNodeRect spreads the whole nodes map on every
// call, so planning N panes one-by-one was O(N^2) allocation churn. This copies nodes at most once,
// writes a new node object only for rects that actually changed (unchanged nodes keep their reference
// so memoized consumers can bail), ignores ids with no node, and returns the SAME state ref when
// nothing changed.
export function updateNodeRects(
  state: EngineLayoutState,
  rects: Record<PaneId, WorldRect>,
): EngineLayoutState {
  let nextNodes: Record<PaneId, PaneNode> | null = null;
  for (const [paneId, rect] of Object.entries(rects)) {
    const node = state.nodes[paneId];
    if (!node || rectsEqual(node.rect, rect)) continue;
    if (!nextNodes) nextNodes = { ...state.nodes };
    nextNodes[paneId] = { ...node, rect };
  }
  if (!nextNodes) return state;
  return { ...state, nodes: nextNodes };
}

export function markNodeClosing(state: EngineLayoutState, paneId: PaneId): EngineLayoutState {
  const node = state.nodes[paneId];
  if (!node) return state;
  return {
    ...state,
    // Closing the focused pane clears the selection; it does not hop to a neighbour. An operator
    // close should never silently re-target focus onto a pane they did not pick.
    focusedPaneId: state.focusedPaneId === paneId ? null : state.focusedPaneId,
    nodes: { ...state.nodes, [paneId]: { ...node, lifecycle: "closing" } },
  };
}

export function removeNode(state: EngineLayoutState, paneId: PaneId): EngineLayoutState {
  const { [paneId]: _removed, ...nodes } = state.nodes;
  return {
    ...state,
    nodes,
    order: state.order.filter((id) => id !== paneId),
    focusedPaneId: state.focusedPaneId === paneId ? null : state.focusedPaneId,
  };
}

/** Splice paneId to a clamped index; pure, shared by movePaneOrder and tentative planning. */
export function splicePaneOrder(order: readonly PaneId[], paneId: PaneId, index: number): PaneId[] {
  const next = order.filter((id) => id !== paneId);
  next.splice(Math.max(0, Math.min(index, next.length)), 0, paneId);
  return next;
}

/** The only mutation through which user intent edits the committed sequence. */
export function movePaneOrder(
  state: EngineLayoutState,
  paneId: PaneId,
  index: number,
): EngineLayoutState {
  if (!state.nodes[paneId]) return state;
  return { ...state, order: splicePaneOrder(state.order, paneId, index) };
}

/** Self-heal a persisted order: drop unknown and duplicate ids, append missing ones. */
export function normalizeLayoutOrder(
  state: EngineLayoutState,
  persisted: readonly PaneId[] | undefined,
): EngineLayoutState {
  const known: PaneId[] = [];
  for (const id of persisted ?? []) {
    if (state.nodes[id] !== undefined && !known.includes(id)) known.push(id);
  }
  const missing = Object.keys(state.nodes).filter((id) => !known.includes(id));
  return { ...state, order: [...known, ...missing] };
}

export function setViewport(state: EngineLayoutState, viewport: CanvasViewport): EngineLayoutState {
  return { ...state, viewport: { ...viewport, scale: clampScale(viewport.scale) } };
}

export const FRAME_FRACTION = 0.8;

// Pure camera op (no React, no hook): the target viewport so `rect` is centered and fills
// `fraction` of the screen `bounds`. Used by the lab store for framing and Fit to content.
// Reuses the transform contract screen = world * scale + pan and the engine clampScale bounds.
export function frameRectViewport(
  rect: WorldRect,
  bounds: ViewportBounds,
  fraction = FRAME_FRACTION,
): CanvasViewport {
  const scale = clampScale(
    fraction * Math.min(bounds.width / rect.width, bounds.height / rect.height),
  );
  const centerX = rect.x + rect.width / 2;
  const centerY = rect.y + rect.height / 2;
  return {
    scale,
    panX: bounds.width / 2 - centerX * scale,
    panY: bounds.height / 2 - centerY * scale,
  };
}
