import { describe, expect, it } from "vitest";
import {
  createInitialEngineLayoutState,
  createPaneNode,
  type PaneNode,
  upsertNode,
} from "../../engine";
import { openPaneIds, planLayout } from "./layoutPlanning";

const RECT = { x: 0, y: 0, width: 100, height: 100 };
const BOUNDS = { width: 800, height: 600 };

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

  it("planLayout honors a paneIdsOverride without mutating the committed order", () => {
    const layout = threePaneLayout();
    const planned = planLayout(layout, BOUNDS, "grid-fit", {}, false, null, undefined, [
      "c",
      "a",
      "b",
    ]);
    expect(planned.order).toEqual(["a", "b", "c"]);
    expect(planned.nodes.c?.rect).toEqual(
      planLayout(layout, BOUNDS, "grid-fit", {}, false).nodes.a?.rect,
    );
  });
});
