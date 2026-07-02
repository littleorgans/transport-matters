import { describe, expect, it } from "vitest";
import {
  createInitialEngineLayoutState,
  createPaneNode,
  type PaneNode,
  upsertNode,
} from "../../engine";
import { registerLayout } from "../../engine/layout";
import { openPaneIds, planLayout } from "./layoutPlanning";

const RECT = { x: 0, y: 0, width: 100, height: 100 };
function threePaneLayout() {
  let layout = createInitialEngineLayoutState();
  for (const id of ["a", "b", "c"]) layout = upsertNode(layout, createPaneNode(id, RECT, 1));
  return layout;
}

describe("planLayout rounding", () => {
  it("rounds every planned rect to whole world pixels, regardless of strategy math", () => {
    registerLayout({
      id: "test-fractional",
      label: "Fractional fixture",
      controls: [],
      defaults: {},
      plan: ({ paneIds }) => ({
        rects: Object.fromEntries(
          paneIds.map((paneId, index) => [
            paneId,
            { x: 64.297 + index, y: 31.5, width: 359.7003, height: 280.4 },
          ]),
        ),
      }),
    });

    const planned = planLayout(
      threePaneLayout(),
      { width: 1600, height: 1000 },
      "test-fractional",
      {},
      false,
    );

    for (const paneId of ["a", "b", "c"]) {
      const rect = (planned.nodes[paneId] as PaneNode).rect;
      expect(Number.isInteger(rect.x), `${paneId}.x = ${rect.x}`).toBe(true);
      expect(Number.isInteger(rect.y), `${paneId}.y = ${rect.y}`).toBe(true);
      expect(Number.isInteger(rect.width), `${paneId}.width = ${rect.width}`).toBe(true);
      expect(Number.isInteger(rect.height), `${paneId}.height = ${rect.height}`).toBe(true);
    }
    expect((planned.nodes.a as PaneNode).rect).toEqual({ x: 64, y: 32, width: 360, height: 280 });
  });
});

describe("ordered planning", () => {
  it("openPaneIds walks the order", () => {
    let layout = threePaneLayout();
    layout = { ...layout, order: ["c", "a", "b"] };
    expect(openPaneIds(layout)).toEqual(["c", "a", "b"]);
  });

  it("openPaneIds filters non-open lifecycles", () => {
    let layout = threePaneLayout();
    layout = { ...layout, order: ["c", "a", "b"] };
    layout = {
      ...layout,
      nodes: { ...layout.nodes, a: { ...(layout.nodes.a as PaneNode), lifecycle: "closed" } },
    };
    expect(openPaneIds(layout)).toEqual(["c", "b"]);
  });
});
