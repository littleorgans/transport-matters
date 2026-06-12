import { describe, expect, it } from "vitest";
import { localDayProgress } from "./dayCycle";

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
