import { describe, expect, it } from "vitest";
import { clockDayToScene, localDayProgress, sceneDayProgress, sceneDayToClock } from "./dayCycle";

describe("localDayProgress", () => {
  it("maps local midnight to 0", () => {
    expect(localDayProgress(new Date(2026, 5, 13, 0, 0, 0))).toBe(0);
  });

  it("maps local noon to 0.5", () => {
    expect(localDayProgress(new Date(2026, 5, 13, 12, 0, 0))).toBe(0.5);
  });

  it("stays below 1 at the end of the day", () => {
    const value = localDayProgress(new Date(2026, 5, 13, 23, 59, 59));
    expect(value).toBeGreaterThan(0.99);
    expect(value).toBeLessThan(1);
  });
});

describe("sceneDayProgress", () => {
  it("maps clock noon to the scene's high sun", () => {
    expect(sceneDayProgress(new Date(2026, 5, 13, 12, 0, 0))).toBe(0.25);
  });

  it("maps clock midnight into the scene's night, not its dawn", () => {
    expect(sceneDayProgress(new Date(2026, 5, 13, 0, 0, 0))).toBe(0.75);
  });

  it("maps 6am to the scene's dawn at 0", () => {
    expect(sceneDayProgress(new Date(2026, 5, 13, 6, 0, 0))).toBe(0);
  });
});

describe("clock and scene domain converters", () => {
  it("round-trip across the whole range", () => {
    for (const clock of [0, 0.1, 0.25, 0.5, 0.75, 0.999]) {
      expect(sceneDayToClock(clockDayToScene(clock))).toBeCloseTo(clock);
    }
  });
});
