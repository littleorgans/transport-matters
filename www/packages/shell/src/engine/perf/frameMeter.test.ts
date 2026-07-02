import { describe, expect, it } from "vitest";
import { summarizeFrameDeltas } from "./frameMeter";

describe("summarizeFrameDeltas", () => {
  it("reports p95 and max frame deltas", () => {
    expect(summarizeFrameDeltas([16, 17, 15, 30, 16])).toEqual({
      frames: 5,
      maxDeltaMs: 30,
      p95DeltaMs: 30,
    });
  });

  it("handles empty captures", () => {
    expect(summarizeFrameDeltas([])).toEqual({ frames: 0, maxDeltaMs: 0, p95DeltaMs: 0 });
  });
});
