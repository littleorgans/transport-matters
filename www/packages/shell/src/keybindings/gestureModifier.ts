export type CanvasGestureModifier = "Shift" | "Space";

export const DEFAULT_CANVAS_GESTURE_MODIFIER: CanvasGestureModifier = "Shift";
export const CANVAS_GESTURE_MODIFIERS: readonly CanvasGestureModifier[] = ["Shift", "Space"];

export function isCanvasGestureModifier(value: unknown): value is CanvasGestureModifier {
  return value === "Shift" || value === "Space";
}
