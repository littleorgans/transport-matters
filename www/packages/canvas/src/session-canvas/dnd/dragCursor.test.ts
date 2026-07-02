import { afterEach, describe, expect, it } from "vitest";
import { paneDragCursorMode, setPaneDragCursor } from "./dragCursor";

describe("paneDragCursorMode", () => {
  it("is deliver while the drop target is a terminal, move otherwise", () => {
    expect(paneDragCursorMode({ kind: "terminal", paneId: "t", label: "Claude-1" })).toBe(
      "deliver",
    );
    expect(paneDragCursorMode({ kind: "surface" })).toBe("move");
    expect(paneDragCursorMode({ kind: "hint" })).toBe("move");
    expect(paneDragCursorMode(null)).toBe("move");
  });
});

describe("setPaneDragCursor", () => {
  afterEach(() => setPaneDragCursor(null));

  it("drives the body attribute the cursor CSS keys off", () => {
    setPaneDragCursor("move");
    expect(document.body.dataset.paneDragCursor).toBe("move");

    setPaneDragCursor("deliver");
    expect(document.body.dataset.paneDragCursor).toBe("deliver");

    setPaneDragCursor(null);
    expect(document.body.dataset.paneDragCursor).toBeUndefined();
  });
});
