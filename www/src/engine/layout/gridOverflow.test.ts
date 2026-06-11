import { describe, expect, it } from "vitest";
import { listLayouts, resolveLayout } from "./index";
import { type GridOverflowParams, planGridOverflow } from "./strategies/gridOverflow";

const DEFAULTS: GridOverflowParams = {
  minW: 300,
  minH: 220,
  maxH: 320,
  aspect: 4 / 3,
  gap: 16,
};

const VIEWPORT = { width: 932, height: 600 };

function ids(n: number): string[] {
  return Array.from({ length: n }, (_value, index) => `p${index}`);
}

function plan(n: number, viewport = VIEWPORT, params = DEFAULTS) {
  return planGridOverflow({ paneIds: ids(n), viewport }, params);
}

describe("planGridOverflow", () => {
  it("returns an empty plan for N=0", () => {
    expect(plan(0).rects).toEqual({});
  });

  it("derives column count from the region width", () => {
    const { frame, reason, rects } = plan(4);
    expect(reason).toBe("grid-overflow 3x2");
    expect(rects.p0).toEqual({ x: 0, y: 0, width: 300, height: 225 });
    expect(rects.p1).toEqual({ x: 316, y: 0, width: 300, height: 225 });
    expect(rects.p2).toEqual({ x: 632, y: 0, width: 300, height: 225 });
    expect(rects.p3).toEqual({ x: 0, y: 241, width: 300, height: 225 });
    expect(frame).toEqual({ x: 0, y: 0, width: 932, height: 600 });
  });

  it("keeps cell size fixed while rows overflow", () => {
    const four = plan(4);
    const twelve = plan(12);
    expect(twelve.reason).toBe("grid-overflow 3x4");
    expect(twelve.rects.p0).toEqual(four.rects.p0);
    expect(twelve.rects.p11).toEqual({ x: 632, y: 723, width: 300, height: 225 });
  });

  it("reports a frame height beyond the viewport when content overflows", () => {
    const { frame } = plan(12);
    expect(frame?.height).toBe(948);
    expect(frame?.height ?? 0).toBeGreaterThan(VIEWPORT.height);
    expect(frame?.width).toBe(VIEWPORT.width);
  });

  it("clamps cell height to the configured band", () => {
    const minClamped = plan(1, VIEWPORT, { ...DEFAULTS, aspect: 2 });
    const maxClamped = plan(1, VIEWPORT, { ...DEFAULTS, aspect: 0.5 });
    expect(minClamped.rects.p0?.height).toBe(DEFAULTS.minH);
    expect(maxClamped.rects.p0?.height).toBe(DEFAULTS.maxH);
  });

  it("is present in the strategy registry with auto-renderable controls", () => {
    const strategy = resolveLayout("grid-overflow");
    expect(listLayouts().map((entry) => entry.id)).toContain("grid-overflow");
    expect(strategy.label).toBe("Grid (overflow)");
    expect(strategy.defaults).toEqual(DEFAULTS);
    expect(strategy.controls.map((control) => control.key)).toEqual([
      "minW",
      "minH",
      "maxH",
      "aspect",
      "gap",
    ]);
  });
});
