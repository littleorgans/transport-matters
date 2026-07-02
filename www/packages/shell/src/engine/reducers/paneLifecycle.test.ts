import { describe, expect, it } from "vitest";
import { moveRect, resizeRect } from "./paneLifecycle";

const RECT = { x: 64, y: 32, width: 360, height: 280 };
const MINIMUM = { width: 300, height: 220 };

describe("moveRect", () => {
  it("quantizes fractional world deltas to whole pixels", () => {
    // screen deltas divided by the camera scale are fractional; per-tick
    // subpixel positions leave compositor ghost trails (same fix family as
    // dndPanePosition)
    expect(moveRect(RECT, 128.2051, -10.25)).toEqual({ ...RECT, x: 192, y: 22 });
  });

  it("keeps whole results exact", () => {
    expect(moveRect(RECT, 10, 20)).toEqual({ ...RECT, x: 74, y: 52 });
  });
});

describe("resizeRect", () => {
  it("quantizes fractional world deltas to whole pixels", () => {
    expect(resizeRect(RECT, 64.1025, 12.82, MINIMUM)).toEqual({
      ...RECT,
      width: 424,
      height: 293,
    });
  });

  it("clamps to the minimum after quantizing", () => {
    expect(resizeRect(RECT, -100.5, -100.5, MINIMUM)).toEqual({
      ...RECT,
      width: 300,
      height: 220,
    });
  });
});
