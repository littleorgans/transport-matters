import type { EngineLayoutState, PaneId, WorldRect } from "../types";
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
}

export function LayoutCanvas({
  layout,
  label,
  renderPane,
  setViewport,
  onFocusPane,
  onMovePane,
  onResizePane,
  titleIdForPane,
}: LayoutCanvasProps) {
  const { bindViewport, handleWheel, handleKeyDown } = useCanvasViewport(layout.viewport, {
    setViewport,
  });
  const nodes = Object.values(layout.nodes).filter((node) => node.lifecycle !== "closed");

  return (
    <section
      {...bindViewport()}
      aria-label={label}
      className="canvas-viewport"
      onKeyDown={handleKeyDown}
      onWheel={handleWheel}
      role="application"
      // biome-ignore lint/a11y/noNoninteractiveTabindex: The canvas viewport owns keyboard pan and zoom shortcuts.
      tabIndex={0}
    >
      <div
        className="canvas-world"
        data-canvas-scale={layout.viewport.scale}
        data-canvas-world="true"
        style={{
          transform: `translate3d(${layout.viewport.panX}px, ${layout.viewport.panY}px, 0) scale(${layout.viewport.scale})`,
        }}
      >
        {nodes.map((node) => (
          <PaneFrame
            focused={layout.focusedPaneId === node.paneId}
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
      </div>
    </section>
  );
}
