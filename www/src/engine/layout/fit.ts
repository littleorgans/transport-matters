import type { ViewportBounds } from "../types";

// Shared fit-scale math so the grid-fit planner's column SCORING and the lab's Fit-to-content
// camera zoom can never drift. Returns the largest scale (capped at 1) that makes content of
// `contentWidth` x `contentHeight` fit inside `bounds`; 1 means it already fits without zooming
// out. The planner SIMULATES this scale to score column counts; the lab applies it to the camera.
export function fitScale(
  contentWidth: number,
  contentHeight: number,
  bounds: ViewportBounds,
): number {
  if (contentWidth <= 0 || contentHeight <= 0) return 1;
  return Math.min(1, bounds.width / contentWidth, bounds.height / contentHeight);
}
