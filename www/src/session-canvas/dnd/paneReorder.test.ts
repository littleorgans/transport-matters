import { beforeEach, describe, expect, it, vi } from "vitest";
import type { EngineLayoutState } from "../../engine";
import type { CanvasPaneRef } from "../model/paneRecords";
import { registerPasteHandle } from "../viewers/terminal/pasteRegistry";
import { useDropTargetStore } from "./dropTargetStore";
import { createPaneReorder } from "./paneReorder";

const RECT_A = { x: 0, y: 0, width: 100, height: 100 };
const RECT_B = { x: 120, y: 0, width: 100, height: 100 };
const RECT_C = { x: 0, y: 120, width: 100, height: 100 };
const RECT_D = { x: 120, y: 120, width: 100, height: 100 };
const MOVED_BEFORE_A = { x: -80, y: 0, width: 100, height: 100 };
const MOVED_OVER_A = { x: -20, y: 0, width: 100, height: 100 };
const MOVED_AFTER_B = { x: 240, y: 0, width: 100, height: 100 };
const MOVED_BEFORE_C = { x: -80, y: 120, width: 100, height: 100 };
const RESOURCE_REF = {
  kind: "resource",
  owner: "local",
  source: "path",
  path: "/t/x.png",
} satisfies CanvasPaneRef;

function layout(
  order: string[],
  rects: Partial<Record<"a" | "b" | "c" | "d", typeof RECT_A>> = {},
): EngineLayoutState {
  return {
    mode: "floating",
    viewport: { panX: 0, panY: 0, scale: 1 },
    order,
    focusedPaneId: null,
    nodes: {
      a: { paneId: "a", lifecycle: "open", rect: rects.a ?? RECT_A, z: 1, pinned: false },
      b: { paneId: "b", lifecycle: "open", rect: rects.b ?? RECT_B, z: 2, pinned: false },
      c: { paneId: "c", lifecycle: "open", rect: rects.c ?? RECT_C, z: 3, pinned: false },
      d: { paneId: "d", lifecycle: "open", rect: rects.d ?? RECT_D, z: 4, pinned: false },
    },
  };
}

describe("paneReorder", () => {
  beforeEach(() => useDropTargetStore.setState({ target: null }));

  function deps(overrides = {}) {
    return {
      getLayout: () => layout(["a", "b", "c", "d"]),
      contentRefFor: () => RESOURCE_REF,
      titleFor: (paneId: string) => paneId,
      commitReorder: vi.fn(),
      cancelReorder: vi.fn(),
      ...overrides,
    };
  }

  it("keeps clicks and pre-threshold moves inert", () => {
    const d = deps();
    const reorder = createPaneReorder(d);

    reorder.onMove("b", RECT_B);
    reorder.onMove("b", {
      x: RECT_B.x + 3,
      y: RECT_B.y,
      width: RECT_B.width,
      height: RECT_B.height,
    });
    reorder.onMoveEnd("b", {
      x: RECT_B.x + 3,
      y: RECT_B.y,
      width: RECT_B.width,
      height: RECT_B.height,
    });

    expect(d.commitReorder).not.toHaveBeenCalled();
    expect(d.cancelReorder).not.toHaveBeenCalled();
    expect(useDropTargetStore.getState().target).toBeNull();
  });

  it("writes a slot indicator on each active move without mutating store deps", () => {
    const d = deps();
    const reorder = createPaneReorder(d);

    reorder.onMove("b", RECT_B);
    reorder.onMove("b", MOVED_BEFORE_A);

    expect(d.commitReorder).not.toHaveBeenCalled();
    expect(d.cancelReorder).not.toHaveBeenCalled();
    expect(useDropTargetStore.getState().target).toEqual({
      kind: "slot",
      rect: { x: RECT_A.x, y: RECT_A.y, width: 0, height: RECT_A.height },
    });
    expect(reorder.isActive()).toBe(true);

    reorder.onMove("b", MOVED_AFTER_B);
    expect(useDropTargetStore.getState().target).toEqual({
      kind: "slot",
      rect: { x: RECT_A.x + RECT_A.width, y: RECT_A.y, width: 0, height: RECT_A.height },
    });
  });

  it("release commits the freshly computed before-first index", () => {
    const d = deps();
    const reorder = createPaneReorder(d);

    reorder.onMove("b", RECT_B);
    reorder.onMove("b", MOVED_AFTER_B);
    reorder.onMoveEnd("b", MOVED_BEFORE_A);

    expect(d.commitReorder).toHaveBeenCalledWith("b", 0);
    expect(d.cancelReorder).not.toHaveBeenCalled();
  });

  it("release commits the after-last index", () => {
    const d = deps();
    const reorder = createPaneReorder(d);

    reorder.onMove("a", RECT_A);
    reorder.onMove("a", { x: 240, y: 120, width: 100, height: 100 });
    reorder.onMoveEnd("a", { x: 240, y: 120, width: 100, height: 100 });

    expect(d.commitReorder).toHaveBeenCalledWith("a", 3);
  });

  it("release commits the row-wrap insertion index", () => {
    const d = deps();
    const reorder = createPaneReorder(d);

    reorder.onMove("a", RECT_A);
    reorder.onMove("a", MOVED_BEFORE_C);
    reorder.onMoveEnd("a", MOVED_BEFORE_C);

    expect(d.commitReorder).toHaveBeenCalledWith("a", 1);
  });

  it("same-order release is a full no-op", () => {
    const d = deps({ getLayout: () => layout(["a", "b"]) });
    const reorder = createPaneReorder(d);

    reorder.onMove("b", RECT_B);
    reorder.onMove("b", { x: 124, y: 4, width: 100, height: 100 });
    reorder.onMoveEnd("b", { x: 124, y: 4, width: 100, height: 100 });

    expect(d.commitReorder).not.toHaveBeenCalled();
    expect(d.cancelReorder).not.toHaveBeenCalled();
  });

  it("release over a paste-handle pane delivers and leaves order untouched", () => {
    const paste = vi.fn();
    const unregister = registerPasteHandle("a", paste);
    const d = deps();
    const reorder = createPaneReorder(d);

    reorder.onMove("b", RECT_B);
    reorder.onMove("b", MOVED_OVER_A);
    expect(useDropTargetStore.getState().target).toEqual({
      kind: "terminal",
      paneId: "a",
      label: "a",
    });

    reorder.onMoveEnd("b", MOVED_OVER_A);

    expect(paste).toHaveBeenCalledWith("/t/x.png");
    expect(d.commitReorder).not.toHaveBeenCalled();
    expect(d.cancelReorder).not.toHaveBeenCalled();
    expect(useDropTargetStore.getState().target).toBeNull();
    unregister();
  });

  it("escape cancels the frozen drag and clears the slot indicator", () => {
    const d = deps({ contentRefFor: () => undefined });
    const reorder = createPaneReorder(d);

    reorder.onMove("b", RECT_B);
    reorder.onMove("b", MOVED_BEFORE_A);
    reorder.onCancel("b");

    expect(d.cancelReorder).toHaveBeenCalledTimes(1);
    expect(d.commitReorder).not.toHaveBeenCalled();
    expect(useDropTargetStore.getState().target).toBeNull();
    expect(reorder.isActive()).toBe(false);
  });

  it("refreshes frozen insertion geometry when open pane membership changes", () => {
    let removedFirstPane = false;
    const d = deps({
      getLayout: () => layout(removedFirstPane ? ["b", "c", "d"] : ["b", "a", "c", "d"]),
      contentRefFor: () => undefined,
    });
    const reorder = createPaneReorder(d);

    reorder.onMove("b", RECT_B);
    reorder.onMove("b", MOVED_BEFORE_C);
    expect(useDropTargetStore.getState().target).toEqual({
      kind: "slot",
      rect: { x: RECT_C.x, y: RECT_C.y, width: 0, height: RECT_C.height },
    });

    removedFirstPane = true;
    reorder.onMove("b", { x: 60, y: 120, width: 100, height: 100 });

    expect(useDropTargetStore.getState().target).toEqual({
      kind: "slot",
      rect: {
        x: (RECT_C.x + RECT_C.width + RECT_D.x) / 2,
        y: RECT_D.y,
        width: 0,
        height: RECT_D.height,
      },
    });
  });
});
