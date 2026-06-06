import type { CanvasViewport, EngineLayoutState, PaneId, PaneNode, WorldRect } from "../types";

export const DEFAULT_CANVAS_VIEWPORT: CanvasViewport = Object.freeze({
  panX: 0,
  panY: 0,
  scale: 1,
});

const MIN_SCALE = 0.45;
const MAX_SCALE = 1.8;
const Z_STEP = 1;

export function createInitialEngineLayoutState(): EngineLayoutState {
  return {
    mode: "floating",
    viewport: DEFAULT_CANVAS_VIEWPORT,
    nodes: {},
    focusedPaneId: null,
  };
}

export function clampScale(scale: number): number {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale));
}

export function nextPaneZ(nodes: Record<PaneId, PaneNode>): number {
  const highest = Object.values(nodes).reduce((max, node) => Math.max(max, node.z), 0);
  return highest + Z_STEP;
}

export function upsertNode(state: EngineLayoutState, node: PaneNode): EngineLayoutState {
  return {
    ...state,
    nodes: { ...state.nodes, [node.paneId]: node },
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

export function markNodeClosing(state: EngineLayoutState, paneId: PaneId): EngineLayoutState {
  const node = state.nodes[paneId];
  if (!node) return state;
  return {
    ...state,
    focusedPaneId:
      state.focusedPaneId === paneId ? nearestPaneId(state, paneId) : state.focusedPaneId,
    nodes: { ...state.nodes, [paneId]: { ...node, lifecycle: "closing" } },
  };
}

export function removeNode(state: EngineLayoutState, paneId: PaneId): EngineLayoutState {
  const { [paneId]: _removed, ...nodes } = state.nodes;
  return {
    ...state,
    nodes,
    focusedPaneId: state.focusedPaneId === paneId ? firstOpenPaneId(nodes) : state.focusedPaneId,
  };
}

export function setViewport(state: EngineLayoutState, viewport: CanvasViewport): EngineLayoutState {
  return { ...state, viewport: { ...viewport, scale: clampScale(viewport.scale) } };
}

export function panViewport(
  viewport: CanvasViewport,
  deltaX: number,
  deltaY: number,
): CanvasViewport {
  return {
    ...viewport,
    panX: viewport.panX + deltaX,
    panY: viewport.panY + deltaY,
  };
}

export function zoomViewportAt(
  viewport: CanvasViewport,
  factor: number,
  screenX: number,
  screenY: number,
): CanvasViewport {
  const nextScale = clampScale(viewport.scale * factor);
  const worldX = (screenX - viewport.panX) / viewport.scale;
  const worldY = (screenY - viewport.panY) / viewport.scale;
  return {
    panX: screenX - worldX * nextScale,
    panY: screenY - worldY * nextScale,
    scale: nextScale,
  };
}

function firstOpenPaneId(nodes: Record<PaneId, PaneNode>): PaneId | null {
  return Object.values(nodes).find((node) => node.lifecycle === "open")?.paneId ?? null;
}

function nearestPaneId(state: EngineLayoutState, removedPaneId: PaneId): PaneId | null {
  const removed = state.nodes[removedPaneId];
  if (!removed) return firstOpenPaneId(state.nodes);
  const removedCenter = centerOf(removed.rect);
  let nearest: { paneId: PaneId; distance: number } | null = null;
  for (const node of Object.values(state.nodes)) {
    if (node.paneId === removedPaneId || node.lifecycle !== "open") continue;
    const center = centerOf(node.rect);
    const distance = Math.hypot(center.x - removedCenter.x, center.y - removedCenter.y);
    if (!nearest || distance < nearest.distance) nearest = { paneId: node.paneId, distance };
  }
  return nearest?.paneId ?? null;
}

function centerOf(rect: WorldRect): { x: number; y: number } {
  return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
}
