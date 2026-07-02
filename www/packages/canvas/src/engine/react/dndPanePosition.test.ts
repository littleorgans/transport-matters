import { describe, expect, it } from "vitest";
import { dndPanePosition } from "./PaneFrame";

const RECT = { x: 64.297, y: 31.5, width: 360, height: 280 };

describe("dndPanePosition", () => {
  it("renders the exact planner rect when no dnd transform is live", () => {
    expect(dndPanePosition(RECT, null)).toEqual({ x: 64.297, y: 31.5 });
  });

  it("quantizes the composed position to whole pixels during a drag", () => {
    // fractional base + fractional world delta -> integer translate, so the
    // compositor's damage rects track the moving pane (ghost-trail fix)
    expect(dndPanePosition(RECT, { x: 328.0003, y: -10.25 })).toEqual({ x: 392, y: 21 });
    expect(dndPanePosition(RECT, { x: 0, y: 0 })).toEqual({ x: 64, y: 32 });
  });
});
