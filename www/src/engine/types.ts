export type PaneId = string;
export type LayoutMode = "floating" | "tiling" | "focus";
export type PaneLifecycle = "open" | "closing" | "closed";

export interface WorldRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface CanvasViewport {
  panX: number;
  panY: number;
  scale: number;
}

export interface PaneNode {
  paneId: PaneId;
  lifecycle: PaneLifecycle;
  rect: WorldRect;
  z: number;
  pinned: boolean;
}

export interface EngineLayoutState {
  mode: LayoutMode;
  viewport: CanvasViewport;
  nodes: Record<PaneId, PaneNode>;
  /** User-controlled pane sequence; strategies consume it via openPaneIds. */
  order: PaneId[];
  focusedPaneId: PaneId | null;
}

export interface ViewportBounds {
  width: number;
  height: number;
}
