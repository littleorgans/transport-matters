import { beforeEach, describe, expect, it, vi } from "vitest";
import type { EngineLayoutState } from "../../engine";
import type { CanvasPaneRef } from "../model/paneRecords";
import { registerPasteHandle } from "../viewers/terminal/pasteRegistry";
import { useDropTargetStore } from "./dropTargetStore";
import { createPaneDndCallbacks } from "./paneDndCallbacks";

const RECT_A = { x: 0, y: 0, width: 100, height: 100 };
const RECT_B = { x: 120, y: 0, width: 100, height: 100 };
const RECT_C = { x: 0, y: 120, width: 100, height: 100 };
const RECT_D = { x: 120, y: 120, width: 100, height: 100 };
const RESOURCE_REF = {
  kind: "resource",
  owner: "local",
  source: "path",
  path: "/t/x.png",
} satisfies CanvasPaneRef;

function layout(order = ["a", "b", "c", "d"]): EngineLayoutState {
  return {
    mode: "floating",
    viewport: { panX: 0, panY: 0, scale: 1 },
    order,
    focusedPaneId: null,
    nodes: {
      a: { paneId: "a", lifecycle: "open", rect: RECT_A, z: 1, pinned: false },
      b: { paneId: "b", lifecycle: "open", rect: RECT_B, z: 2, pinned: false },
      c: { paneId: "c", lifecycle: "open", rect: RECT_C, z: 3, pinned: false },
      d: { paneId: "d", lifecycle: "open", rect: RECT_D, z: 4, pinned: false },
    },
  };
}

// Identity viewport + zero surface origin: client coordinates ARE world
// coordinates, so fixtures can speak in pane-rect terms directly.
function deps(overrides = {}) {
  return {
    getLayout: () => layout(),
    contentRefFor: (): CanvasPaneRef | undefined => RESOURCE_REF,
    titleFor: (paneId: string) => paneId,
    commitReorder: vi.fn(),
    getSurfaceOrigin: () => ({ left: 0, top: 0 }),
    getExpandedPaneId: (): string | null => null,
    ...overrides,
  };
}

function dragEvent(activeId: string, at: { x: number; y: number }, overId: string | null) {
  return {
    active: { id: activeId },
    over: overId === null ? null : { id: overId },
    activatorEvent: { clientX: at.x, clientY: at.y },
    delta: { x: 0, y: 0 },
  } as never;
}

describe("createPaneDndCallbacks", () => {
  beforeEach(() => useDropTargetStore.setState({ target: null }));

  it("release over another pane commits that pane's order index", () => {
    const d = deps();
    const callbacks = createPaneDndCallbacks(d);

    callbacks.onDragStart(dragEvent("b", { x: 170, y: 50 }, null));
    const result = callbacks.onDragEnd(dragEvent("b", { x: 50, y: 170 }, "a"));

    expect(d.commitReorder).toHaveBeenCalledWith("b", 0);
    expect(result.settle).toBe(true);
  });

  it("release commits the after-last index", () => {
    const d = deps();
    const callbacks = createPaneDndCallbacks(d);

    const result = callbacks.onDragEnd(dragEvent("a", { x: 240, y: 170 }, "d"));

    expect(d.commitReorder).toHaveBeenCalledWith("a", 3);
    expect(result.settle).toBe(true);
  });

  it("release over the pane's own slot is a full no-op", () => {
    const d = deps();
    const callbacks = createPaneDndCallbacks(d);

    const result = callbacks.onDragEnd(dragEvent("b", { x: 170, y: 50 }, "b"));

    expect(d.commitReorder).not.toHaveBeenCalled();
    expect(result.settle).toBe(false);
  });

  it("release with no over target is a no-op", () => {
    const d = deps();
    const callbacks = createPaneDndCallbacks(d);

    const result = callbacks.onDragEnd(dragEvent("b", { x: 999, y: 999 }, null));

    expect(d.commitReorder).not.toHaveBeenCalled();
    expect(result.settle).toBe(false);
  });

  it("release over a paste-handle pane delivers and leaves order untouched", () => {
    const paste = vi.fn();
    const unregister = registerPasteHandle("a", paste);
    const d = deps();
    const callbacks = createPaneDndCallbacks(d);

    // pointer inside a's rect; over reports a as the reorder target too, but
    // delivery wins for locator panes
    const result = callbacks.onDragEnd(dragEvent("b", { x: 50, y: 50 }, "a"));

    expect(paste).toHaveBeenCalledWith("/t/x.png");
    expect(d.commitReorder).not.toHaveBeenCalled();
    expect(result.settle).toBe(false);
    expect(useDropTargetStore.getState().target).toBeNull();
    unregister();
  });

  it("release over a paste-handle pane without a locator ref reorders normally", () => {
    const paste = vi.fn();
    const unregister = registerPasteHandle("a", paste);
    const d = deps({ contentRefFor: () => undefined });
    const callbacks = createPaneDndCallbacks(d);

    callbacks.onDragEnd(dragEvent("b", { x: 50, y: 50 }, "a"));

    expect(paste).not.toHaveBeenCalled();
    expect(d.commitReorder).toHaveBeenCalledWith("b", 0);
    unregister();
  });

  it("move over a paste-handle pane highlights the delivery target for locator panes", () => {
    const unregister = registerPasteHandle("a", vi.fn());
    const callbacks = createPaneDndCallbacks(deps());

    callbacks.onDragMove(dragEvent("b", { x: 50, y: 50 }, null));
    expect(useDropTargetStore.getState().target).toEqual({
      kind: "terminal",
      paneId: "a",
      label: "a",
    });

    callbacks.onDragMove(dragEvent("b", { x: 170, y: 170 }, null));
    expect(useDropTargetStore.getState().target).toBeNull();
    unregister();
  });

  it("move never highlights for panes without a locator ref", () => {
    const unregister = registerPasteHandle("a", vi.fn());
    const callbacks = createPaneDndCallbacks(deps({ contentRefFor: () => undefined }));

    callbacks.onDragMove(dragEvent("b", { x: 50, y: 50 }, null));

    expect(useDropTargetStore.getState().target).toBeNull();
    unregister();
  });

  // The expanded hero is registered as a droppable so collision reports it as
  // `over`, but it is a delivery-only target: a release over it either pastes
  // (locator + paste handle) or does nothing. It NEVER commits a reorder, even
  // though it keeps a position in layout.order.
  it("release over the expanded hero without a locator is a full no-op", () => {
    const d = deps({
      contentRefFor: () => undefined,
      getExpandedPaneId: () => "a",
    });
    const callbacks = createPaneDndCallbacks(d);

    const result = callbacks.onDragEnd(dragEvent("b", { x: 50, y: 50 }, "a"));

    expect(d.commitReorder).not.toHaveBeenCalled();
    expect(result.settle).toBe(false);
  });

  it("release over the expanded hero with a locator but no paste handle never reorders", () => {
    const d = deps({ getExpandedPaneId: () => "a" });
    const callbacks = createPaneDndCallbacks(d);

    const result = callbacks.onDragEnd(dragEvent("b", { x: 50, y: 50 }, "a"));

    expect(d.commitReorder).not.toHaveBeenCalled();
    expect(result.settle).toBe(false);
  });

  it("release over the expanded hero with a locator and paste handle delivers", () => {
    const paste = vi.fn();
    const unregister = registerPasteHandle("a", paste);
    const d = deps({ getExpandedPaneId: () => "a" });
    const callbacks = createPaneDndCallbacks(d);

    const result = callbacks.onDragEnd(dragEvent("b", { x: 50, y: 50 }, "a"));

    expect(paste).toHaveBeenCalledWith("/t/x.png");
    expect(d.commitReorder).not.toHaveBeenCalled();
    expect(result.settle).toBe(false);
    unregister();
  });

  it("cancel commits nothing, clears the target, and settles the lifted pane home", () => {
    const unregister = registerPasteHandle("a", vi.fn());
    const d = deps();
    const callbacks = createPaneDndCallbacks(d);

    callbacks.onDragMove(dragEvent("b", { x: 50, y: 50 }, null));
    const result = callbacks.onDragCancel();

    expect(d.commitReorder).not.toHaveBeenCalled();
    expect(result.settle).toBe(true);
    expect(useDropTargetStore.getState().target).toBeNull();
    unregister();
  });

  it("converts the release point through viewport and surface origin", () => {
    const paste = vi.fn();
    const unregister = registerPasteHandle("a", paste);
    const d = deps({
      getLayout: () => ({
        ...layout(),
        viewport: { panX: 60, panY: 40, scale: 0.5 },
      }),
      getSurfaceOrigin: () => ({ left: 10, top: 20 }),
    });
    const callbacks = createPaneDndCallbacks(d);

    // world (50, 50) -> surface (60 + 50*0.5, 40 + 50*0.5) = (85, 65) -> client (95, 85)
    callbacks.onDragEnd(dragEvent("b", { x: 95, y: 85 }, "a"));

    expect(paste).toHaveBeenCalledWith("/t/x.png");
    expect(d.commitReorder).not.toHaveBeenCalled();
    unregister();
  });
});
