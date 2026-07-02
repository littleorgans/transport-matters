import { describe, expect, it } from "vitest";
import { roundWorldPoint, roundWorldRect } from "./geometry";

describe("roundWorldRect", () => {
  it("rounds every field to the nearest whole pixel", () => {
    expect(roundWorldRect({ x: 64.297, y: 31.5, width: 359.7003, height: 280.4 })).toEqual({
      x: 64,
      y: 32,
      width: 360,
      height: 280,
    });
  });

  it("returns the same reference when the rect is already whole", () => {
    const rect = { x: 64, y: 32, width: 360, height: 280 };
    expect(roundWorldRect(rect)).toBe(rect);
  });
});

describe("roundWorldPoint", () => {
  it("rounds both axes to the nearest whole pixel", () => {
    expect(roundWorldPoint({ x: 392.297, y: -10.25 })).toEqual({ x: 392, y: -10 });
  });
});
