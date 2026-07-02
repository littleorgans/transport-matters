import { describe, expect, it } from "vitest";
import { planGridFit } from "./strategies/gridFit";
import { CANVAS_LAYOUT_MARGIN, type PlanInput } from "./types";

const DEFAULTS = {
  minW: 320,
  minH: 240,
  gap: 24,
  margin: CANVAS_LAYOUT_MARGIN, // 64: the single-source prod-wide layout margin this test guards
  targetAspect: 4 / 3,
  packing: "fill" as const,
  lastRow: "left" as const,
};
const VIEWPORT = { width: 1600, height: 1000 };
const VIEWPORT_12 = { width: 1600, height: 1076 }; // 4x3 cellH = (1076-176)/3 = 300 (exact; 176 = 2*64 + 2*24)
const VIEWPORT_5 = { width: 1604, height: 1000 }; // 3x2 cellW = (1604-176)/3 = 476 (exact; 176 = 2*64 + 2*24)

function ids(n: number): string[] {
  return Array.from({ length: n }, (_value, index) => `p${index}`);
}

function plan(n: number, viewport = VIEWPORT, params = DEFAULTS) {
  const input: PlanInput = { paneIds: ids(n), viewport };
  return planGridFit(input, params);
}

describe("planGridFit", () => {
  it("returns an empty plan for N=0", () => {
    expect(plan(0).rects).toEqual({});
  });

  it("fills the work area for N=1", () => {
    expect(plan(1).rects.p0).toEqual({ x: 64, y: 64, width: 1472, height: 872 });
  });

  it("places two panes side by side", () => {
    const { rects } = plan(2);
    expect(rects.p0).toEqual({ x: 64, y: 64, width: 724, height: 872 });
    expect(rects.p1).toEqual({ x: 812, y: 64, width: 724, height: 872 });
  });

  it("uses a 2x2 grid for four panes", () => {
    const { rects, reason } = plan(4);
    expect(reason).toBe("grid-fit 2x2");
    expect(rects.p0).toEqual({ x: 64, y: 64, width: 724, height: 424 });
    expect(rects.p3).toEqual({ x: 812, y: 512, width: 724, height: 424 });
  });

  // The zoom-aware selector picks WIDER panes (3x2) over the old 2x3 because they fill the width.
  it("produces the exact 3x2 table for N=5 (last row left-aligned)", () => {
    const { rects, reason } = planGridFit({ paneIds: ids(5), viewport: VIEWPORT_5 }, DEFAULTS);
    expect(reason).toBe("grid-fit 3x2");
    expect(rects.p0).toEqual({ x: 64, y: 64, width: 476, height: 424 });
    expect(rects.p1).toEqual({ x: 564, y: 64, width: 476, height: 424 });
    expect(rects.p2).toEqual({ x: 1064, y: 64, width: 476, height: 424 });
    expect(rects.p3).toEqual({ x: 64, y: 512, width: 476, height: 424 });
    expect(rects.p4).toEqual({ x: 564, y: 512, width: 476, height: 424 }); // partial row, left
  });

  it("produces the exact 4x3 table for N=12", () => {
    const { rects, reason } = planGridFit({ paneIds: ids(12), viewport: VIEWPORT_12 }, DEFAULTS);
    expect(reason).toBe("grid-fit 4x3");
    expect(rects.p0).toEqual({ x: 64, y: 64, width: 350, height: 300 });
    expect(rects.p3).toEqual({ x: 1186, y: 64, width: 350, height: 300 });
    expect(rects.p4).toEqual({ x: 64, y: 388, width: 350, height: 300 });
    expect(rects.p11).toEqual({ x: 1186, y: 712, width: 350, height: 300 });
  });

  // Backs the §2.3 spec table at its 1600x1000 design space (the exact-table tests above use
  // integer-friendly viewport variants; this asserts the documented values directly).
  it("matches the §2.3 spec table at the 1600x1000 design space", () => {
    const five = plan(5);
    expect(five.reason).toBe("grid-fit 3x2");
    expect(five.rects.p0?.width).toBeCloseTo(474.67, 1); // (1600-48-128)/3
    expect(five.rects.p0?.height).toBe(424);
    const twelve = plan(12);
    expect(twelve.reason).toBe("grid-fit 4x3");
    expect(twelve.rects.p0?.width).toBe(350);
    expect(twelve.rects.p0?.height).toBeCloseTo(274.67, 1); // (1000-48-128)/3
  });

  // Regression for the horizontal-slack bug: 13 panes that used to land 4x4 @ zoom ~0.78 (empty band
  // on the right) now land 5x3 and fill the full width (width floored at 380). The fit is width-bound
  // (~0.97), so the height also fills the leftover vertical space — cells grow from base 336 to ~347.
  it("fills both axes for the 13-pane case (5x3 fills width, height fills the rest)", () => {
    const params = {
      minW: 380,
      minH: 320,
      gap: 20,
      margin: 0,
      targetAspect: 4 / 3,
      packing: "fill" as const,
      lastRow: "left" as const,
    };
    const { rects, reason } = planGridFit(
      { paneIds: ids(13), viewport: { width: 1920, height: 1048 } },
      params,
    );
    expect(reason).toBe("grid-fit 5x3");
    expect(rects.p0?.x).toBe(0);
    expect(rects.p0?.width).toBe(380); // width floored; 5 columns fill the 1920 width
    expect(rects.p4?.x).toBe(1600); // last column reaches the right edge (4 * (380 + 20))
    expect(rects.p0?.height).toBeCloseTo(346.92, 1); // height fills the vertical slack (> 336 base)
    expect(rects.p5?.y).toBeCloseTo(366.92, 1); // row 2 starts after the filled cellH + gap
  });

  // Height-bound fill: 10 panes land 5x2, the min-height floor (240) makes the grid taller than the
  // 400-tall viewport, so Fit-to-content is height-bound (scale 400/480 ≈ 0.833). Cells widen from
  // the base 200 to 240 so the grid fills the width at that scale — no left/right negative space.
  it("widens cells to fill the width when the fit is height-bound", () => {
    const params = {
      minW: 200,
      minH: 240,
      gap: 0,
      margin: 0,
      targetAspect: 4 / 3,
      packing: "fill" as const,
      lastRow: "left" as const,
    };
    const { rects, reason } = planGridFit(
      { paneIds: ids(10), viewport: { width: 1000, height: 400 } },
      params,
    );
    expect(reason).toBe("grid-fit 5x2");
    expect(rects.p0).toEqual({ x: 0, y: 0, width: 240, height: 240 }); // widened 200 -> 240
    expect(rects.p1?.x).toBe(240); // cells tile flush; grid spans the full 1000 width at fit scale
  });

  it("center-aligns a partial last row when configured", () => {
    const { rects } = planGridFit(
      { paneIds: ids(5), viewport: VIEWPORT_5 },
      { ...DEFAULTS, lastRow: "center" },
    );
    // 3x2: row 2 has 2 of 3 panes, centred. rowWidth = 2*476 + 24 = 976; usableW = 1604-128 = 1476;
    // startX = 64 + (1476-976)/2 = 314.
    expect(rects.p3?.x).toBe(314);
    expect(rects.p4?.x).toBe(814);
  });

  it("floors the binding axis at min and fills the cross axis on overflow (camera fit is lab-side)", () => {
    const { rects, reason } = planGridFit(
      { paneIds: ids(12), viewport: { width: 900, height: 1000 } },
      DEFAULTS,
    );
    expect(reason).toBe("grid-fit 3x4");
    // Width-bound: width sits on the 320 min floor; height fills the vertical slack (> 240 base) so
    // there is no top/bottom negative space once the camera zooms to fit.
    expect(Object.values(rects).every((rect) => rect.width === 320)).toBe(true);
    expect(rects.p0?.height).toBeCloseTo(265.56, 1);
    expect(rects.p0?.height ?? 0).toBeGreaterThan(240);
    const distinctRows = new Set(Object.values(rects).map((rect) => rect.y)).size;
    expect(distinctRows).toBe(4);
  });
});

// The `packing` toggle: "aspect" picks columns by closeness to targetAspect instead of by size,
// so crowded grids add a column rather than going wide/stubby. (Default "fill" is covered above.)
describe("planGridFit packing=aspect", () => {
  const ASPECT = { ...DEFAULTS, packing: "aspect" as const };
  const WIDE = { width: 1920, height: 960 };

  it("keeps 8 panes at 4x2 (no regression vs fill)", () => {
    expect(planGridFit({ paneIds: ids(8), viewport: WIDE }, ASPECT).reason).toBe("grid-fit 4x2");
  });

  it("fixes the stubby 11-pane case: 5x3 instead of a wide 4x3", () => {
    const { reason, rects } = planGridFit(
      { paneIds: ids(11), viewport: WIDE },
      { ...ASPECT, minW: 380 },
    );
    expect(reason).toBe("grid-fit 5x3");
    expect(rects.p0?.x).toBe(64);
    expect(rects.p0?.y).toBe(64);
    expect(rects.p0?.width).toBe(380); // 5 columns (width floored), not a wide 4x3
  });
});
