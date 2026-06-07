import { describe, expect, it } from "vitest";
import { framedPaneId, resetCanvasLabStoreForTests, useCanvasLabStore } from "./canvasLabStore";

const store = useCanvasLabStore.getState;

describe("canvasLabStore framing", () => {
  it("frames a pane (stashing the prior viewport) and toggles back on a second call", () => {
    resetCanvasLabStoreForTests();
    store().addPane(); // lab-1
    store().addPane(); // lab-2
    const priorViewport = store().layout.viewport;

    store().framePane("lab-1");
    expect(framedPaneId(store().framing)).toBe("lab-1");
    expect(store().framing.overview).toEqual(priorViewport); // pre-framing camera snapshotted
    expect(store().layout.viewport).not.toEqual(priorViewport); // camera moved

    store().framePane("lab-1"); // toggle -> unframe
    expect(framedPaneId(store().framing)).toBeNull();
    expect(store().layout.viewport).toEqual(priorViewport); // restored
  });

  it("steps back through nested frames one level per unframe", () => {
    resetCanvasLabStoreForTests();
    store().addPane(); // lab-1
    store().addPane(); // lab-2
    store().addPane(); // lab-3
    store().addPane(); // lab-4
    const overview = store().layout.viewport;

    store().framePane("lab-3");
    const framed3 = store().layout.viewport;
    expect(framed3).not.toEqual(overview);
    expect(store().layout.focusedPaneId).toBe("lab-3"); // framed pane is selected

    store().framePane("lab-4"); // frame a second pane without unframing the first
    expect(framedPaneId(store().framing)).toBe("lab-4");
    expect(store().framing.stack).toHaveLength(2);
    expect(store().layout.focusedPaneId).toBe("lab-4");

    store().unframe(); // pops lab-4 -> back to the framed lab-3 view, and re-selects lab-3
    expect(framedPaneId(store().framing)).toBe("lab-3");
    expect(store().layout.viewport).toEqual(framed3);
    expect(store().layout.focusedPaneId).toBe("lab-3");

    store().unframe(); // pops lab-3 -> back to the overview; lab-3 keeps the selection
    expect(framedPaneId(store().framing)).toBeNull();
    expect(store().layout.viewport).toEqual(overview);
    expect(store().layout.focusedPaneId).toBe("lab-3");
  });

  it("re-frames the underlying pane on unframe even after the camera was panned away", () => {
    // Regression: frame A, manually pan the camera elsewhere, frame B, unframe. Stepping back to A
    // must re-frame A from its rect so it is on-screen. Restoring the viewport captured when B was
    // framed (the panned-away camera) would leave the re-selected A off-screen.
    resetCanvasLabStoreForTests();
    for (let index = 0; index < 4; index += 1) store().addPane(); // lab-1 .. lab-4

    store().framePane("lab-4");
    const framed4 = store().layout.viewport;

    store().setViewport({ panX: -5000, panY: -5000, scale: 0.5 }); // user pans far from lab-4
    expect(store().layout.viewport).not.toEqual(framed4);

    store().framePane("lab-1"); // frame a second pane from the panned-away camera
    store().unframe(); // pop lab-1 -> must re-frame lab-4, not restore the panned-away camera

    expect(framedPaneId(store().framing)).toBe("lab-4");
    expect(store().layout.focusedPaneId).toBe("lab-4");
    expect(store().layout.viewport).toEqual(framed4); // lab-4 is framed and visible again
  });

  it("does not frame when only one pane is open", () => {
    resetCanvasLabStoreForTests();
    store().addPane(); // lab-1 only
    store().framePane("lab-1");
    expect(framedPaneId(store().framing)).toBeNull();
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
  it("zooms the camera to fit the margin-padded grid frame", () => {
    resetCanvasLabStoreForTests();
    for (let index = 0; index < 12; index += 1) store().addPane();
    store().setBounds({ width: 900, height: 1000 });
    // The selector picks 3x4 (gridW 1008 x gridH 1032). The lab fits the frame — the grid padded by
    // margin (48) on every side, 1104 x 1128 — so that margin survives as on-screen breathing room:
    // min(1, 900/1104, 1000/1128) = 900/1104 ≈ 0.815.
    expect(store().layout.viewport.scale).toBeCloseTo(0.815, 2);
  });

  it("resets a stale zoom-out once the content fits again (no lingering slack)", () => {
    resetCanvasLabStoreForTests();
    for (let index = 0; index < 12; index += 1) store().addPane();
    store().setBounds({ width: 900, height: 1000 }); // overflow -> scale < 1
    expect(store().layout.viewport.scale).toBeLessThan(1);
    store().setBounds({ width: 2200, height: 1400 }); // now fits -> must snap back to 1, centered
    expect(store().layout.viewport.scale).toBe(1);
    expect(store().layout.viewport.panX).toBe(0);
    expect(store().layout.viewport.panY).toBe(0);
  });
});
