import { describe, expect, it } from "vitest";
import { insertionIndexAtWorldPoint } from "./insertionIndex";

// 2x2 row-major grid: row 0 y=0..100, row 1 y=120..220; columns x=0..100, x=120..220.
const GRID = [
  { paneId: "a", rect: { x: 0, y: 0, width: 100, height: 100 } },
  { paneId: "b", rect: { x: 120, y: 0, width: 100, height: 100 } },
  { paneId: "c", rect: { x: 0, y: 120, width: 100, height: 100 } },
  { paneId: "d", rect: { x: 120, y: 120, width: 100, height: 100 } },
];

describe("insertionIndexAtWorldPoint", () => {
  it("returns 0 for empty rects (lifting the sole pane)", () => {
    expect(insertionIndexAtWorldPoint([], { x: 50, y: 50 })).toBe(0);
  });

  it("before-first and after-last", () => {
    expect(insertionIndexAtWorldPoint(GRID, { x: 5, y: 40 })).toBe(0);
    expect(insertionIndexAtWorldPoint(GRID, { x: 219, y: 200 })).toBe(4);
  });

  it("bias on the x axis within the row band", () => {
    expect(insertionIndexAtWorldPoint(GRID, { x: 90, y: 50 })).toBe(1); // after a's center
    expect(insertionIndexAtWorldPoint(GRID, { x: 40, y: 50 })).toBe(0); // before a's center
  });

  it("row-wrap equivalence: end of row 0 equals before first of row 1", () => {
    expect(insertionIndexAtWorldPoint(GRID, { x: 219, y: 50 })).toBe(2);
    expect(insertionIndexAtWorldPoint(GRID, { x: 5, y: 160 })).toBe(2);
  });

  it("selects the nearest row band for points between rows", () => {
    // Row centers sit at y=50 and y=170; 115 is nearer row 1 (55 vs 65).
    expect(insertionIndexAtWorldPoint(GRID, { x: 40, y: 115 })).toBe(2);
  });

  it("degenerates to a single row (singleRow strips)", () => {
    const row = GRID.slice(0, 2);
    expect(insertionIndexAtWorldPoint(row, { x: 110, y: 50 })).toBe(1);
  });
});
