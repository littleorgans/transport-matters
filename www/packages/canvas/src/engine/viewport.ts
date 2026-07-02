import type { CanvasViewport } from "./types";

export const MIN_SCALE = 0.45;
export const MAX_SCALE = 1.8;
export const WHEEL_ZOOM_FACTOR = 0.92;
export const KEYBOARD_PAN_STEP = 64;
export const KEYBOARD_ZOOM_IN = 1.1;
export const KEYBOARD_ZOOM_OUT = 0.9;

export function clampScale(scale: number): number {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale));
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
