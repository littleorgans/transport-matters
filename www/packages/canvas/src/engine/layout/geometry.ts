import type { WorldRect } from "../types";

// World geometry quantization, shared by every producer of rendered pane
// geometry: planner output (planLayout), per-tick user gestures (moveRect,
// resizeRect), and the dnd drag compose (dndPanePosition). Whole world pixels
// keep compositor damage rects honest; fractional translates inside the
// scaled canvas leave ghost trails behind moving panes.

export function roundWorldRect(rect: WorldRect): WorldRect {
  const x = Math.round(rect.x);
  const y = Math.round(rect.y);
  const width = Math.round(rect.width);
  const height = Math.round(rect.height);
  if (x === rect.x && y === rect.y && width === rect.width && height === rect.height) return rect;
  return { x, y, width, height };
}

export function roundWorldPoint(point: { x: number; y: number }): { x: number; y: number } {
  return { x: Math.round(point.x), y: Math.round(point.y) };
}
