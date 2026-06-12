import type { ReactElement } from "react";
import type { EngineLayoutState } from "../../engine";
import { useDropTargetStore } from "../dnd/dropTargetStore";

// Screen-space highlight for the active drop target (LayoutCanvas overlay
// slot, like PaneDock). Terminal targets outline the hit pane's rect mapped
// through the viewport camera; "surface" outlines the whole canvas; "hint"
// is rendered by CanvasDropHint instead (browser file drags cannot resolve).
export function CanvasDropTargetOverlay({
  layout,
}: {
  layout: EngineLayoutState;
}): ReactElement | null {
  const target = useDropTargetStore((state) => state.target);
  if (target === null || target.kind === "hint") return null;
  if (target.kind === "surface") {
    return <div aria-hidden="true" className="canvas-drop-target canvas-drop-target--surface" />;
  }
  if (target.kind === "slot") {
    const { panX, panY, scale } = layout.viewport;
    const style = {
      left: target.rect.x * scale + panX,
      top: target.rect.y * scale + panY,
      width: target.rect.width * scale,
      height: target.rect.height * scale,
    };
    return (
      <div
        aria-hidden="true"
        className="canvas-drop-target canvas-drop-target--slot"
        style={style}
      />
    );
  }
  const node = layout.nodes[target.paneId];
  if (!node) return null;
  const { panX, panY, scale } = layout.viewport;
  const style = {
    left: node.rect.x * scale + panX,
    top: node.rect.y * scale + panY,
    width: node.rect.width * scale,
    height: node.rect.height * scale,
  };
  return (
    <div
      aria-hidden="true"
      className="canvas-drop-target canvas-drop-target--terminal"
      style={style}
    >
      <span className="canvas-drop-target__label">Paste into {target.label}</span>
    </div>
  );
}
