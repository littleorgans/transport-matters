import { describe, expect, it } from "vitest";
import { listLayouts } from "./index";

// The acceptance heart (spec §6): a strategy file dropped into ./strategies/ is auto-discovered by
// import.meta.glob and registered with ZERO other edits. single-row is exactly such a drop-in.
describe("layout strategy auto-discovery (extensibility proof)", () => {
  it("registers every strategy file with zero other edits", () => {
    const registeredIds = listLayouts().map((strategy) => strategy.id);
    expect(registeredIds).toContain("grid-fit");
    expect(registeredIds).toContain("single-row");
  });

  it("exposes auto-renderable, validated controls for the dropped-in strategy", () => {
    const singleRow = listLayouts().find((strategy) => strategy.id === "single-row");
    expect(singleRow).toBeDefined();
    expect(singleRow?.controls.length).toBeGreaterThan(0);
    const defaults = singleRow?.defaults ?? {};
    expect(singleRow?.controls.every((control) => control.key in defaults)).toBe(true);
  });
});
