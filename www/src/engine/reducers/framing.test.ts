import { describe, expect, it } from "vitest";
import { frameRectViewport } from "./layoutState";

describe("frameRectViewport", () => {
  it("centers a pane and scales it toward 80% of the viewport (clamped at max)", () => {
    const viewport = frameRectViewport(
      { x: 100, y: 100, width: 400, height: 300 },
      { width: 1000, height: 800 },
    );
    // 0.8 * min(1000/400, 800/300) = 0.8 * 2.5 = 2.0 -> clampScale max 1.8
    expect(viewport.scale).toBeCloseTo(1.8);
    expect(viewport.panX).toBeCloseTo(500 - 300 * 1.8); // screenCenterX - rectCenterX * scale
    expect(viewport.panY).toBeCloseTo(400 - 250 * 1.8);
  });

  it("zooms out to fit an oversized rect, respecting the clampScale floor", () => {
    const viewport = frameRectViewport(
      { x: 0, y: 0, width: 4000, height: 3000 },
      { width: 1000, height: 800 },
      1,
    );
    // raw = min(1000/4000, 800/3000) = 0.25 -> clampScale floor 0.45
    expect(viewport.scale).toBeCloseTo(0.45);
  });
});
