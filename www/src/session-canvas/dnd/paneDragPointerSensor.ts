import { PointerSensor } from "@dnd-kit/core";
import { dragModeForTarget } from "../../engine";

// Activation gate for pane sortable drags. Replaces the base PointerSensor
// activator so non-move targets never start a dnd-kit drag: resize handles and
// the canvas pan (Shift+drag from anywhere, including over panes) stay with
// @use-gesture, interactive controls inside bodyDrag panes stay clickable.
// The target policy is dragModeForTarget, shared with the engine's gesture
// code, reading the pane's bodyDrag opt-in from its frame data attribute.
export function shouldStartPaneDrag(event: PointerEvent): boolean {
  if (!event.isPrimary || event.button !== 0) return false;
  if (event.shiftKey) return false;
  const target = event.target;
  if (!(target instanceof Element)) return false;
  const frame = target.closest<HTMLElement>("[data-pane-frame='true']");
  if (frame === null) return false;
  const bodyDrag = frame.dataset.paneBodyDrag === "true";
  return dragModeForTarget(target, bodyDrag) === "move";
}

export class PaneDragPointerSensor extends PointerSensor {
  static override activators = [
    {
      eventName: "onPointerDown" as const,
      handler: ({ nativeEvent }: { nativeEvent: PointerEvent }) => shouldStartPaneDrag(nativeEvent),
    },
  ];
}
