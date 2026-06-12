import { describe, expect, it } from "vitest";
import {
  createInitialEngineLayoutState,
  createPaneNode,
  type PaneNode,
  upsertNode,
} from "../../engine";
import { openPaneIds } from "./layoutPlanning";

const RECT = { x: 0, y: 0, width: 100, height: 100 };
function threePaneLayout() {
  let layout = createInitialEngineLayoutState();
  for (const id of ["a", "b", "c"]) layout = upsertNode(layout, createPaneNode(id, RECT, 1));
  return layout;
}

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
