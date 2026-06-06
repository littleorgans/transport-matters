import type { PaneId, PaneNode, WorldRect } from "../types";

export function createPaneNode(
  paneId: PaneId,
  rect: WorldRect,
  z: number,
  pinned = false,
): PaneNode {
  return {
    paneId,
    lifecycle: "open",
    pinned,
    rect,
    z,
  };
}

export function moveRect(rect: WorldRect, deltaX: number, deltaY: number): WorldRect {
  return {
    ...rect,
    x: rect.x + deltaX,
    y: rect.y + deltaY,
  };
}

export function resizeRect(
  rect: WorldRect,
  deltaX: number,
  deltaY: number,
  minimum: Pick<WorldRect, "width" | "height">,
): WorldRect {
  return {
    ...rect,
    width: Math.max(minimum.width, rect.width + deltaX),
    height: Math.max(minimum.height, rect.height + deltaY),
  };
}
