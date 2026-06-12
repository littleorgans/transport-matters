import { roundWorldRect } from "../layout/geometry";
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

// Gesture deltas arrive as screen pixels divided by the camera scale, so they
// are fractional; both reducers quantize through roundWorldRect (see
// engine/layout/geometry.ts for why whole world pixels matter).
export function moveRect(rect: WorldRect, deltaX: number, deltaY: number): WorldRect {
  return roundWorldRect({
    ...rect,
    x: rect.x + deltaX,
    y: rect.y + deltaY,
  });
}

export function resizeRect(
  rect: WorldRect,
  deltaX: number,
  deltaY: number,
  minimum: Pick<WorldRect, "width" | "height">,
): WorldRect {
  return roundWorldRect({
    ...rect,
    width: Math.max(minimum.width, rect.width + deltaX),
    height: Math.max(minimum.height, rect.height + deltaY),
  });
}
