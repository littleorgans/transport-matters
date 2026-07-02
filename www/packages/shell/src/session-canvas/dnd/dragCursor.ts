import type { DropTarget } from "./dropTargetStore";

// Cursor language for a live pane drag: grabbing while moving, the copy
// cursor (arrow with a plus badge) while the drop would DELIVER into a
// paste-handle pane: the pane is not moving in, its content is copied in.
// The mode rides a body attribute because the pointer crosses many elements
// mid-drag; pane-dock.css holds the matching cursor rules.
export type PaneDragCursorMode = "move" | "deliver";

export function paneDragCursorMode(target: DropTarget | null): PaneDragCursorMode {
  return target?.kind === "terminal" ? "deliver" : "move";
}

export function setPaneDragCursor(mode: PaneDragCursorMode | null): void {
  if (mode === null) delete document.body.dataset.paneDragCursor;
  else document.body.dataset.paneDragCursor = mode;
}
