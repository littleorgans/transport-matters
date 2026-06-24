/** Ambient compatibility facade for the canonical engine viewport contract. */
export type { CanvasViewport, WorldRect } from "../../engine/types";
export {
  clampScale,
  KEYBOARD_PAN_STEP,
  KEYBOARD_ZOOM_IN,
  KEYBOARD_ZOOM_OUT,
  MAX_SCALE,
  MIN_SCALE,
  panViewport,
  WHEEL_ZOOM_FACTOR,
  zoomViewportAt,
} from "../../engine/viewport";
