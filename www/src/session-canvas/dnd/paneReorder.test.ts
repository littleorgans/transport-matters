import { beforeEach, describe, expect, it, vi } from "vitest";
import type { EngineLayoutState } from "../../engine";
import type { CanvasPaneRef } from "../model/paneRecords";
import { registerPasteHandle } from "../viewers/terminal/pasteRegistry";
import { useDropTargetStore } from "./dropTargetStore";
import { createPaneReorder } from "./paneReorder";

const RECT_A = { x: 0, y: 0, width: 100, height: 100 };
const RECT_B = { x: 120, y: 0, width: 100, height: 100 };
const RESOURCE_REF = {
  kind: "resource",
  owner: "local",
  source: "path",
  path: "/t/x.png",
} satisfies CanvasPaneRef;

function layout(order: string[]): EngineLayoutState {
  return {
    mode: "floating",
    viewport: { panX: 0, panY: 0, scale: 1 },
    order,
    focusedPaneId: null,
    nodes: {
      a: { paneId: "a", lifecycle: "open", rect: RECT_A, z: 1, pinned: false },
      b: { paneId: "b", lifecycle: "open", rect: RECT_B, z: 2, pinned: false },
    },
  };
}

describe("paneReorder", () => {
  beforeEach(() => useDropTargetStore.setState({ target: null }));

  function deps(overrides = {}) {
    return {
      getLayout: () => layout(["a", "b"]),
      contentRefFor: () => RESOURCE_REF,
      titleFor: (paneId: string) => paneId,
      previewReorder: vi.fn(),
      commitReorder: vi.fn(),
      cancelReorder: vi.fn(),
      ...overrides,
    };
  }

  it("previews on index change only, and reports reorder-active", () => {
    const d = deps();
    const reorder = createPaneReorder(d);
    reorder.onMove("b", { x: -10, y: 0, width: 100, height: 100 });
    reorder.onMove("b", { x: -8, y: 0, width: 100, height: 100 });
    expect(d.previewReorder).toHaveBeenCalledTimes(1);
    expect(d.previewReorder).toHaveBeenCalledWith("b", 0);
    expect(reorder.isActive()).toBe(true);
  });

  it("release over a paste-handle pane delivers and cancels the reorder", () => {
    const paste = vi.fn();
    const unregister = registerPasteHandle("a", paste);
    const d = deps();
    const reorder = createPaneReorder(d);
    reorder.onMove("b", { x: -10, y: 0, width: 100, height: 100 });
    reorder.onMoveEnd("b", { x: -10, y: 0, width: 100, height: 100 });
    expect(paste).toHaveBeenCalledWith("/t/x.png");
    expect(d.cancelReorder).toHaveBeenCalled();
    expect(d.commitReorder).not.toHaveBeenCalled();
    unregister();
  });

  it("release elsewhere commits the last index and clears the target", () => {
    const d = deps();
    const reorder = createPaneReorder(d);
    reorder.onMove("b", { x: -10, y: 0, width: 100, height: 100 });
    reorder.onMoveEnd("b", { x: -10, y: 0, width: 100, height: 100 });
    expect(d.commitReorder).toHaveBeenCalledWith("b", 0);
    expect(useDropTargetStore.getState().target).toBeNull();
    expect(reorder.isActive()).toBe(false);
  });

  it("cancel reverts without committing", () => {
    const d = deps();
    const reorder = createPaneReorder(d);
    reorder.onMove("b", { x: -10, y: 0, width: 100, height: 100 });
    reorder.onCancel("b");
    expect(d.cancelReorder).toHaveBeenCalled();
    expect(d.commitReorder).not.toHaveBeenCalled();
  });

  it("a zero-move click neither previews nor commits nor cancels", () => {
    const d = deps();
    const reorder = createPaneReorder(d);
    reorder.onMove("b", RECT_B);
    reorder.onMoveEnd("b", RECT_B);
    expect(d.previewReorder).not.toHaveBeenCalled();
    expect(d.commitReorder).not.toHaveBeenCalled();
    expect(d.cancelReorder).not.toHaveBeenCalled();
  });

  it("dragging away and back home previews the restore and cancels instead of committing", () => {
    const d = deps();
    const reorder = createPaneReorder(d);
    reorder.onMove("b", { x: -10, y: 0, width: 100, height: 100 });
    reorder.onMove("b", RECT_B);
    reorder.onMoveEnd("b", RECT_B);
    expect(d.previewReorder).toHaveBeenLastCalledWith("b", 1);
    expect(d.commitReorder).not.toHaveBeenCalled();
    expect(d.cancelReorder).toHaveBeenCalled();
  });
});
