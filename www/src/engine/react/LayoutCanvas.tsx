import { memo, useMemo } from "react";
import type { EngineLayoutState, PaneId, PaneNode, WorldRect } from "../types";
import { PaneFrame } from "./PaneFrame";
import { type CanvasViewportActions, useCanvasViewport } from "./useCanvasViewport";

export interface LayoutCanvasProps extends CanvasViewportActions {
  layout: EngineLayoutState;
  label: string;
  onFocusPane(paneId: PaneId): void;
  onMovePane(paneId: PaneId, rect: WorldRect): void;
  onResizePane(paneId: PaneId, rect: WorldRect): void;
  titleIdForPane(paneId: PaneId): string;
  renderPane(paneId: PaneId): React.ReactNode;
  // Optional: when true, the world layer gets a transform transition (the lab's camera "fly").
  // Omitted by /canvas, so production behaviour is unchanged.
  framing?: boolean;
}

interface PaneLayerProps {
  nodes: PaneNode[];
  focusedPaneId: PaneId | null;
  instant: boolean;
  onFocusPane(paneId: PaneId): void;
  onMovePane(paneId: PaneId, rect: WorldRect): void;
  onResizePane(paneId: PaneId, rect: WorldRect): void;
  titleIdForPane(paneId: PaneId): string;
  renderPane(paneId: PaneId): React.ReactNode;
}

// The pane subtree, split out and memoized so a pan/zoom (which writes a new viewport every tick and
// re-renders LayoutCanvas) does NOT re-render every pane and its content. The memo bails while its
// props are referentially stable: `nodes` is memoized on layout.nodes (untouched by viewport writes),
// the callbacks are stable store actions, and `renderPane` MUST be a useCallback in the caller. It
// re-renders only when nodes change (add/close/move/resize/focus z-bump), focus moves (focusedPaneId,
// drives the focus ring), or instant flips (zoom/fly, drives the size-FLIP snap). focus and organize
// still re-render the whole layer; per-pane memo is a possible future step.
const PaneLayer = memo(function PaneLayer({
  nodes,
  focusedPaneId,
  instant,
  onFocusPane,
  onMovePane,
  onResizePane,
  titleIdForPane,
  renderPane,
}: PaneLayerProps) {
  return (
    <>
      {nodes.map((node) => (
        <PaneFrame
          focused={focusedPaneId === node.paneId}
          instant={instant}
          key={node.paneId}
          node={node}
          onFocus={onFocusPane}
          onMove={onMovePane}
          onResize={onResizePane}
          titleId={titleIdForPane(node.paneId)}
        >
          {renderPane(node.paneId)}
        </PaneFrame>
      ))}
    </>
  );
});

export function LayoutCanvas({
  layout,
  label,
  renderPane,
  setViewport,
  onFocusPane,
  onMovePane,
  onResizePane,
  titleIdForPane,
  framing = false,
}: LayoutCanvasProps) {
  const { bindViewport, handleWheel, handleKeyDown, panReady, panning, zooming } =
    useCanvasViewport(layout.viewport, { setViewport });
  // Memoized on layout.nodes so a viewport-only update (setViewport preserves the nodes ref) keeps the
  // same array and the memoized PaneLayer below skips re-rendering the panes.
  const nodes = useMemo(
    () => Object.values(layout.nodes).filter((node) => node.lifecycle !== "closed"),
    [layout.nodes],
  );
  // A layout="size" FLIP measures each pane in screen space and inverts the ancestor scale per node,
  // which is cheap at 100% but expensive across many panes once the world is scaled. While zoomed,
  // hold size changes instant: a bulk ORGANIZE (or any reflow) snaps instead of running N FLIPs under
  // scale. Size springs are only worth their cost at 1:1, where the projection is identity. Panes also
  // go instant while the camera flies (framing) or wheel-zooms (zooming) so a FLIP cannot fight the
  // scaling parent and flicker.
  const zoomed = Math.abs(layout.viewport.scale - 1) > 0.001;
  const instant = zooming || framing || zoomed;
  const viewportClassName = [
    "canvas-viewport",
    panReady && "canvas-viewport--pan-ready",
    panning && "canvas-viewport--panning",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <section
      {...bindViewport()}
      aria-label={label}
      className={viewportClassName}
      onKeyDown={handleKeyDown}
      onWheel={handleWheel}
      role="application"
      // biome-ignore lint/a11y/noNoninteractiveTabindex: The canvas viewport owns keyboard pan and zoom shortcuts.
      tabIndex={0}
    >
      <div
        className={framing ? "canvas-world canvas-world--framing" : "canvas-world"}
        data-canvas-scale={layout.viewport.scale}
        data-canvas-world="true"
        style={{
          transform: `translate3d(${layout.viewport.panX}px, ${layout.viewport.panY}px, 0) scale(${layout.viewport.scale})`,
        }}
      >
        <PaneLayer
          focusedPaneId={layout.focusedPaneId}
          instant={instant}
          nodes={nodes}
          onFocusPane={onFocusPane}
          onMovePane={onMovePane}
          onResizePane={onResizePane}
          renderPane={renderPane}
          titleIdForPane={titleIdForPane}
        />
      </div>
    </section>
  );
}
