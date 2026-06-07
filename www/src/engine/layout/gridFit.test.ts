import { describe, expect, it } from "vitest";
import { planGridFit } from "./strategies/gridFit";
import type { PlanInput } from "./types";

const DEFAULTS = {
  minW: 320,
  minH: 240,
  gap: 24,
  margin: 48,
  targetAspect: 4 / 3,
  lastRow: "left" as const,
};
const VIEWPORT = { width: 1600, height: 1000 };
const VIEWPORT_INT = { width: 1600, height: 1044 }; // cellH divides evenly for exact tables

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

  it("turns four panes into a 2x2 grid (aspect cap, not a 4x1 row)", () => {
    const { rects, reason } = plan(4);
    expect(reason).toBe("grid-fit 2x2");
    expect(rects.p0).toEqual({ x: 48, y: 48, width: 740, height: 440 });
    expect(rects.p3).toEqual({ x: 812, y: 512, width: 740, height: 440 });
  });

  // Exact rect tables at an integer-friendly height (cellH = (1044-144)/3 = 300) so every value
  // is checkable, not just the shape.
  it("produces the exact 2x3 table for N=5 (last row left-aligned)", () => {
    const { rects, reason } = planGridFit({ paneIds: ids(5), viewport: VIEWPORT_INT }, DEFAULTS);
    expect(reason).toBe("grid-fit 2x3");
    expect(rects.p0).toEqual({ x: 48, y: 48, width: 740, height: 300 });
    expect(rects.p1).toEqual({ x: 812, y: 48, width: 740, height: 300 });
    expect(rects.p2).toEqual({ x: 48, y: 372, width: 740, height: 300 });
    expect(rects.p3).toEqual({ x: 812, y: 372, width: 740, height: 300 });
    expect(rects.p4).toEqual({ x: 48, y: 696, width: 740, height: 300 }); // partial row, left
  });

  it("produces the exact 4x3 table for N=12", () => {
    const { rects, reason } = planGridFit({ paneIds: ids(12), viewport: VIEWPORT_INT }, DEFAULTS);
    expect(reason).toBe("grid-fit 4x3");
    expect(rects.p0).toEqual({ x: 48, y: 48, width: 358, height: 300 });
    expect(rects.p3).toEqual({ x: 1194, y: 48, width: 358, height: 300 });
    expect(rects.p4).toEqual({ x: 48, y: 372, width: 358, height: 300 });
    expect(rects.p11).toEqual({ x: 1194, y: 696, width: 358, height: 300 });
  });

  it("center-aligns a partial last row when configured", () => {
    const { rects } = planGridFit(
      { paneIds: ids(5), viewport: VIEWPORT },
      { ...DEFAULTS, lastRow: "center" },
    );
    expect(rects.p4?.x).toBe(430);
  });

  it("clamps cell height to minH on vertical overflow (camera fit is lab-side)", () => {
    const { rects } = planGridFit(
      { paneIds: ids(12), viewport: { width: 900, height: 1000 } },
      DEFAULTS,
    );
    const heights = Object.values(rects).map((rect) => rect.height);
    expect(heights.every((height) => height === 240)).toBe(true);
    const distinctRows = new Set(Object.values(rects).map((rect) => rect.y)).size;
    expect(distinctRows).toBe(6);
  });
});
