import { describe, expect, it } from "vitest";
import { resetCanvasLabStoreForTests, useCanvasLabStore } from "./canvasLabStore";

const store = useCanvasLabStore.getState;

describe("canvasLabStore framing", () => {
  it("frames a pane (stashing the prior viewport) and toggles back on a second call", () => {
    resetCanvasLabStoreForTests();
    store().addPane(); // lab-1
    store().addPane(); // lab-2
    const priorViewport = store().layout.viewport;

    store().framePane("lab-1");
    expect(store().framing.framedPaneId).toBe("lab-1");
    expect(store().framing.priorViewport).toEqual(priorViewport);
    expect(store().layout.viewport).not.toEqual(priorViewport); // camera moved

    store().framePane("lab-1"); // toggle -> unframe
    expect(store().framing.framedPaneId).toBeNull();
    expect(store().layout.viewport).toEqual(priorViewport); // restored
  });

  it("does not frame when only one pane is open", () => {
    resetCanvasLabStoreForTests();
    store().addPane(); // lab-1 only
    store().framePane("lab-1");
    expect(store().framing.framedPaneId).toBeNull();
  });

  it("organizes panes through the active strategy on add", () => {
    resetCanvasLabStoreForTests();
    store().addPane();
    store().addPane();
    const rects = Object.values(store().layout.nodes).map((node) => node.rect);
    // grid-fit places two panes side by side: same y, different x.
    expect(rects).toHaveLength(2);
    expect(rects[0]?.y).toBe(rects[1]?.y);
    expect(rects[0]?.x).not.toBe(rects[1]?.x);
  });
});

describe("canvasLabStore setParam validation", () => {
  it("clamps a number param to its control range", () => {
    resetCanvasLabStoreForTests();
    store().setParam("minW", 99999);
    expect(store().params.minW).toBe(640); // grid-fit minW max
    store().setParam("minW", 0);
    expect(store().params.minW).toBe(160); // grid-fit minW min
  });

  it("ignores an unknown key", () => {
    resetCanvasLabStoreForTests();
    store().setParam("bogus", 5);
    expect("bogus" in store().params).toBe(false);
  });

  it("ignores a value whose type does not match the control kind", () => {
    resetCanvasLabStoreForTests();
    store().setParam("minW", "320"); // number control, string value
    expect(store().params.minW).toBe(320); // unchanged default
  });

  it("accepts a valid enum value and rejects an out-of-range one", () => {
    resetCanvasLabStoreForTests();
    store().setParam("lastRow", "center");
    expect(store().params.lastRow).toBe("center");
    store().setParam("lastRow", "diagonal"); // not in options
    expect(store().params.lastRow).toBe("center"); // unchanged
  });
});

describe("canvasLabStore fit to content", () => {
  it("zooms the camera to fit the overflowing grid bounding box", () => {
    resetCanvasLabStoreForTests();
    for (let index = 0; index < 12; index += 1) store().addPane();
    store().setBounds({ width: 900, height: 1000 });
    // The zoom-aware selector picks 3x4 (gridW 1008 x gridH 1032); the lab fits that bbox into the
    // 900x1000 viewport via the SAME shared fitScale: min(1, 900/1008, 1000/1032) = 900/1008 ≈ 0.893.
    expect(store().layout.viewport.scale).toBeCloseTo(0.893, 2);
  });
});
