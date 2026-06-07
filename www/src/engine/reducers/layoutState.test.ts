import { describe, expect, it } from "vitest";
import {
  createInitialEngineLayoutState,
  focusNode,
  markNodeClosing,
  removeNode,
  updateNodeRects,
  upsertNode,
} from "./layoutState";
import { createPaneNode } from "./paneLifecycle";

const RECT = { x: 0, y: 0, width: 100, height: 100 };

function twoPaneState() {
  let state = createInitialEngineLayoutState();
  state = upsertNode(state, createPaneNode("a", RECT, 1));
  state = upsertNode(state, createPaneNode("b", RECT, 2));
  return state;
}

describe("updateNodeRects", () => {
  it("applies many rects in one pass, touching only the panes whose rect changed", () => {
    const state = twoPaneState();
    const aBefore = state.nodes.a;
    const bBefore = state.nodes.b;

    const next = updateNodeRects(state, {
      a: { x: 10, y: 10, width: 100, height: 100 }, // changed
      b: { ...RECT }, // identical value -> must keep its reference
    });

    expect(next).not.toBe(state); // a changed, so a new state ref
    expect(next.nodes.a).not.toBe(aBefore); // changed pane gets a fresh node object
    expect(next.nodes.a?.rect.x).toBe(10);
    expect(next.nodes.b).toBe(bBefore); // unchanged pane keeps its reference (memo can bail)
  });

  it("returns the same state ref when nothing changes and ignores unknown ids", () => {
    const state = twoPaneState();

    const next = updateNodeRects(state, {
      a: { ...RECT }, // identical
      b: { ...RECT }, // identical
      ghost: { x: 5, y: 5, width: 10, height: 10 }, // no such node -> ignored
    });

    expect(next).toBe(state); // pure no-op, same reference
  });
});

describe("closing the focused pane clears the selection", () => {
  it("markNodeClosing nulls focus when the focused pane closes, otherwise leaves it", () => {
    const state = focusNode(twoPaneState(), "a");

    expect(markNodeClosing(state, "a").focusedPaneId).toBeNull(); // focused pane closing -> no selection
    expect(markNodeClosing(state, "b").focusedPaneId).toBe("a"); // closing another keeps focus
  });

  it("removeNode nulls focus when the focused pane is removed, otherwise leaves it", () => {
    const state = focusNode(twoPaneState(), "a");

    expect(removeNode(state, "a").focusedPaneId).toBeNull(); // focused pane gone -> no auto-hop to a neighbour
    expect(removeNode(state, "b").focusedPaneId).toBe("a"); // removing another keeps focus
  });
});
