import { describe, expect, it } from "vitest";
import { clearDropTarget, setDropTarget, useDropTargetStore } from "./dropTargetStore";

describe("dropTargetStore", () => {
  it("sets, replaces, and clears the active target", () => {
    setDropTarget({ kind: "terminal", paneId: "t1", label: "Claude-1" });
    expect(useDropTargetStore.getState().target).toEqual({
      kind: "terminal",
      paneId: "t1",
      label: "Claude-1",
    });
    setDropTarget({ kind: "surface" });
    expect(useDropTargetStore.getState().target).toEqual({ kind: "surface" });
    clearDropTarget();
    expect(useDropTargetStore.getState().target).toBeNull();
  });
});
