import { describe, expect, it } from "vitest";
import { planGridFit } from "./strategies/gridFit";
import type { PlanInput } from "./types";

const DEFAULTS = {
  minW: 320,
  minH: 240,
  gap: 24,
  margin: 48,
  targetAspect: 4 / 3,
  packing: "fill" as const,
  lastRow: "left" as const,
};
const VIEWPORT = { width: 1600, height: 1000 };
const VIEWPORT_12 = { width: 1600, height: 1044 }; // 4x3 cellH = (1044-144)/3 = 300 (exact)
const VIEWPORT_5 = { width: 1602, height: 1000 }; // 3x2 cellW = (1602-144)/3 = 486 (exact)

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
    expect(plan(1).rects.p0).toEqual({ x: 48, y: 48, width: 1504, height: 904 });
  });

  it("places two panes side by side", () => {
    const { rects } = plan(2);
    expect(rects.p0).toEqual({ x: 48, y: 48, width: 740, height: 904 });
    expect(rects.p1).toEqual({ x: 812, y: 48, width: 740, height: 904 });
  });

  it("uses a 2x2 grid for four panes", () => {
    const { rects, reason } = plan(4);
    expect(reason).toBe("grid-fit 2x2");
    expect(rects.p0).toEqual({ x: 48, y: 48, width: 740, height: 440 });
    expect(rects.p3).toEqual({ x: 812, y: 512, width: 740, height: 440 });
  });

  // The zoom-aware selector picks WIDER panes (3x2) over the old 2x3 because they fill the width.
  it("produces the exact 3x2 table for N=5 (last row left-aligned)", () => {
    const { rects, reason } = planGridFit({ paneIds: ids(5), viewport: VIEWPORT_5 }, DEFAULTS);
    expect(reason).toBe("grid-fit 3x2");
    expect(rects.p0).toEqual({ x: 48, y: 48, width: 486, height: 440 });
    expect(rects.p1).toEqual({ x: 558, y: 48, width: 486, height: 440 });
    expect(rects.p2).toEqual({ x: 1068, y: 48, width: 486, height: 440 });
    expect(rects.p3).toEqual({ x: 48, y: 512, width: 486, height: 440 });
    expect(rects.p4).toEqual({ x: 558, y: 512, width: 486, height: 440 }); // partial row, left
  });

  it("produces the exact 4x3 table for N=12", () => {
    const { rects, reason } = planGridFit({ paneIds: ids(12), viewport: VIEWPORT_12 }, DEFAULTS);
    expect(reason).toBe("grid-fit 4x3");
    expect(rects.p0).toEqual({ x: 48, y: 48, width: 358, height: 300 });
    expect(rects.p3).toEqual({ x: 1194, y: 48, width: 358, height: 300 });
    expect(rects.p4).toEqual({ x: 48, y: 372, width: 358, height: 300 });
    expect(rects.p11).toEqual({ x: 1194, y: 696, width: 358, height: 300 });
  });

  // Backs the §2.3 spec table at its 1600x1000 design space (the exact-table tests above use
  // integer-friendly viewport variants; this asserts the documented values directly).
  it("matches the §2.3 spec table at the 1600x1000 design space", () => {
    const five = plan(5);
    expect(five.reason).toBe("grid-fit 3x2");
    expect(five.rects.p0?.width).toBeCloseTo(485.33, 1); // (1600-48-96)/3
    expect(five.rects.p0?.height).toBe(440);
    const twelve = plan(12);
    expect(twelve.reason).toBe("grid-fit 4x3");
    expect(twelve.rects.p0?.width).toBe(358);
    expect(twelve.rects.p0?.height).toBeCloseTo(285.33, 1); // (1000-48-96)/3
  });

  // Regression for the horizontal-slack bug: 13 panes that used to land 4x4 @ zoom ~0.78 (empty
  // band on the right) now fill the full width as 5x3 @ ~0.97 (380x336 world cells).
  it("fills the width for the 13-pane case (5x3, not 4x4)", () => {
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
    expect(rects.p0).toEqual({ x: 0, y: 0, width: 380, height: 336 });
    expect(rects.p4).toEqual({ x: 1600, y: 0, width: 380, height: 336 }); // last column reaches 1980 right edge
    expect(rects.p5).toEqual({ x: 0, y: 356, width: 380, height: 336 });
    expect(rects.p12).toEqual({ x: 800, y: 712, width: 380, height: 336 }); // partial row 3, left
  });

  it("center-aligns a partial last row when configured", () => {
    const { rects } = planGridFit(
      { paneIds: ids(5), viewport: VIEWPORT_5 },
      { ...DEFAULTS, lastRow: "center" },
    );
    // 3x2: row 2 has 2 of 3 panes, centred. rowWidth = 2*486 + 24 = 996; startX = (1506-996)/2 = 255.
    expect(rects.p3?.x).toBe(303);
    expect(rects.p4?.x).toBe(813);
  });

  it("clamps cell size to the min floors on overflow (camera fit is lab-side)", () => {
    const { rects, reason } = planGridFit(
      { paneIds: ids(12), viewport: { width: 900, height: 1000 } },
      DEFAULTS,
    );
    expect(reason).toBe("grid-fit 3x4");
    expect(Object.values(rects).every((rect) => rect.width === 320 && rect.height === 240)).toBe(
      true,
    );
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
    expect(rects.p0).toEqual({ x: 48, y: 48, width: 380, height: 272 });
  });
});
