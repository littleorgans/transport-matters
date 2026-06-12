/**
 * Faithful port of the production camera from transport-matters:
 *   www/src/engine/types.ts            (CanvasViewport)
 *   www/src/engine/reducers/layoutState.ts (clampScale, panViewport, zoomViewportAt)
 *
 * Conventions (must stay identical to production):
 * - panX/panY/scale are CSS px; world → screen: screen = world * scale + pan
 * - .canvas-world gets `translate3d(panX, panY, 0) scale(scale)`, origin 0 0
 * - Pan is Shift+drag, zoom is Shift+wheel at cursor (factor 0.92/tick)
 * - Scale clamps to [0.45, 1.8]
 */
export interface CanvasViewport {
  panX: number;
  panY: number;
  scale: number;
}

export interface WorldRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

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
