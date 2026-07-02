import { describe, expect, it } from "vitest";
import type { EngineLayoutState } from "../../engine";
import {
  closestPaneAtWorldPoint,
  createPlannerRectMeasure,
  createWorldSpaceCollision,
  pointerToWorld,
  sortableTransformToWorld,
} from "./dndSpace";

const VIEWPORT = { panX: 60, panY: 40, scale: 0.78 };

function layout(viewport = VIEWPORT): EngineLayoutState {
  return {
    mode: "floating",
    viewport,
    order: ["a", "b"],
    focusedPaneId: null,
    nodes: {
      a: {
        paneId: "a",
        lifecycle: "open",
        rect: { x: 30, y: 30, width: 140, height: 90 },
        z: 1,
        pinned: false,
      },
      b: {
        paneId: "b",
        lifecycle: "open",
        rect: { x: 186, y: 30, width: 140, height: 90 },
        z: 2,
        pinned: false,
      },
    },
  };
}

describe("pointerToWorld", () => {
  it("is identity under the identity viewport", () => {
    expect(pointerToWorld({ panX: 0, panY: 0, scale: 1 }, { x: 12, y: 34 })).toEqual({
      x: 12,
      y: 34,
    });
  });

  it("undoes pan then scale, matching the canvas transform contract", () => {
    // screen = world * scale + pan, so world = (screen - pan) / scale
    expect(pointerToWorld(VIEWPORT, { x: 60 + 100 * 0.78, y: 40 + 75 * 0.78 })).toEqual({
      x: 100,
      y: 75,
    });
  });
});

describe("createPlannerRectMeasure", () => {
  const measure = createPlannerRectMeasure(() => layout());

  function paneElement(paneId: string): HTMLElement {
    const el = document.createElement("div");
    el.dataset.paneId = paneId;
    return el;
  }

  it("returns the pane's world rect from the store, never the DOM", () => {
    const el = paneElement("b");
    // jsdom would measure 0x0; the planner rect must come from the store
    expect(measure(el)).toEqual({
      top: 30,
      left: 186,
      right: 326,
      bottom: 120,
      width: 140,
      height: 90,
    });
  });

  it("returns a plain object with own enumerable fields (a live DOMRect breaks dnd-kit)", () => {
    const rect = measure(paneElement("a"));
    expect(Object.keys(rect).sort()).toEqual(["bottom", "height", "left", "right", "top", "width"]);
  });

  it("returns a zero rect for an unknown pane id", () => {
    expect(measure(paneElement("ghost"))).toEqual({
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      width: 0,
      height: 0,
    });
  });
});

describe("closestPaneAtWorldPoint", () => {
  const entries = [
    { id: "a", rect: { x: 30, y: 30, width: 140, height: 90 } },
    { id: "b", rect: { x: 186, y: 30, width: 140, height: 90 } },
  ];

  it("returns the containing pane at distance 0", () => {
    expect(closestPaneAtWorldPoint(entries, { x: 190, y: 35 })).toEqual({ id: "b", distance: 0 });
  });

  it("falls back to the nearest rect center over empty canvas", () => {
    const hit = closestPaneAtWorldPoint(entries, { x: 90, y: 200 });
    expect(hit?.id).toBe("a");
    expect(hit?.distance).toBeGreaterThan(0);
  });

  it("returns null with no panes", () => {
    expect(closestPaneAtWorldPoint([], { x: 0, y: 0 })).toBeNull();
  });
});

describe("createWorldSpaceCollision", () => {
  const collision = createWorldSpaceCollision({
    getViewport: () => VIEWPORT,
    getSurfaceOrigin: () => ({ left: 10, top: 20 }),
  });

  const worldRects = new Map([
    ["a", { top: 30, left: 30, right: 170, bottom: 120, width: 140, height: 90 }],
    ["b", { top: 30, left: 186, right: 326, bottom: 120, width: 140, height: 90 }],
  ]);
  const containers = [{ id: "a" }, { id: "b" }] as never[];

  // client = surfaceOrigin + pan + world * scale
  const clientAt = (worldX: number, worldY: number) => ({
    x: 10 + 60 + worldX * 0.78,
    y: 20 + 40 + worldY * 0.78,
  });

  function collide(world: { x: number; y: number }) {
    return collision({
      pointerCoordinates: clientAt(world.x, world.y),
      droppableRects: worldRects,
      droppableContainers: containers,
      active: null,
      collisionRect: null,
    } as never);
  }

  it("prefers the pane directly under the converted pointer", () => {
    // world point inside b, but a's center is nearer to nothing — b wins by containment
    expect(collide({ x: 190, y: 35 }).map((c) => c.id)).toEqual(["b"]);
  });

  it("falls back to the closest center when the pointer is over empty canvas", () => {
    // between the rows, slightly nearer to a's center
    expect(collide({ x: 90, y: 200 }).map((c) => c.id)).toEqual(["a"]);
  });

  it("returns no collisions when there are no droppables", () => {
    const result = collision({
      pointerCoordinates: clientAt(0, 0),
      droppableRects: new Map(),
      droppableContainers: [],
      active: null,
      collisionRect: null,
    } as never);
    expect(result).toEqual([]);
  });

  it("suppresses reorder targeting while the drag point sits on a delivery target", () => {
    // delivery wins over reorder: with no `over`, the sortable strategy stops
    // shifting siblings, so the paste target stays put under the cursor
    const deliveryAware = createWorldSpaceCollision({
      getViewport: () => VIEWPORT,
      getSurfaceOrigin: () => ({ left: 10, top: 20 }),
      getDeliveryTarget: (world, activeId) =>
        activeId === "drag-me" && world.x >= 186 && world.x <= 326 ? "b" : null,
    });
    const args = (world: { x: number; y: number }) =>
      ({
        pointerCoordinates: clientAt(world.x, world.y),
        droppableRects: worldRects,
        droppableContainers: containers,
        active: { id: "drag-me" },
        collisionRect: null,
      }) as never;

    // over the paste-handle pane: no reorder target at all
    expect(deliveryAware(args({ x: 190, y: 35 }))).toEqual([]);
    // off the delivery target: normal reorder targeting resumes
    expect(deliveryAware(args({ x: 40, y: 35 })).map((c) => c.id)).toEqual(["a"]);
  });
});

describe("sortableTransformToWorld", () => {
  it("passes a null transform through", () => {
    expect(sortableTransformToWorld(null, 0.78, false)).toBeNull();
  });

  it("applies sibling strategy deltas raw: they are already world pixels", () => {
    const applied = sortableTransformToWorld(
      { x: 156, y: -106, scaleX: 1, scaleY: 1 },
      0.78,
      false,
    );
    expect(applied).toEqual({ x: 156, y: -106 });
  });

  it("converts the active pointer delta by dividing by scale exactly once", () => {
    for (const scale of [0.5, 0.78, 1, 1.5]) {
      const raw = { x: 121.7, y: 82.7, scaleX: 1, scaleY: 1 };
      const applied = sortableTransformToWorld(raw, scale, true);
      if (applied === null) throw new Error("expected a transform");
      // seam invariant 2: applied * scale == raw (catches skipped AND doubled conversions)
      expect(applied.x * scale).toBeCloseTo(raw.x, 6);
      expect(applied.y * scale).toBeCloseTo(raw.y, 6);
      // regression shapes: skipped (applied == raw) and doubled (applied * scale == raw / scale)
      if (scale !== 1) {
        expect(applied.x).not.toBeCloseTo(raw.x, 6);
        expect(applied.x * scale).not.toBeCloseTo(raw.x / scale, 6);
      }
    }
  });
});
