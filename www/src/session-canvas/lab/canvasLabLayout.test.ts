import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  createInitialEngineLayoutState,
  type EngineLayoutState,
  type PaneId,
  type PaneNode,
  upsertNode,
  type ViewportBounds,
  type WorldRect,
} from "../../engine";
import { resolveLayout } from "../../engine/layout";
import { planLayout } from "./canvasLabLayout";
import { resetCanvasLabStoreForTests, useCanvasLabStore } from "./canvasLabStore";
import {
  composeExpandFrame,
  EXPAND_REMAINDER_STRATEGY_ID,
  planExpandLayout,
  splitExpandColumns,
  translateRect,
  translateRects,
} from "./expandLayout";

const BOUNDS: ViewportBounds = { width: 1000, height: 700 };
const HERO_ID = "hero";
const REMAINDER_IDS = ["p1", "p2", "p3", "p4", "p5"];
const PANE_IDS = [HERO_ID, ...REMAINDER_IDS];

const store = useCanvasLabStore.getState;

function openNode(paneId: PaneId, index: number): PaneNode {
  return {
    paneId,
    lifecycle: "open",
    pinned: false,
    rect: { x: index, y: index, width: 10, height: 10 },
    z: index + 1,
  };
}

function layoutWithPanes(paneIds: readonly PaneId[]): EngineLayoutState {
  return paneIds.reduce(
    (layout, paneId, index) => upsertNode(layout, openNode(paneId, index)),
    createInitialEngineLayoutState(),
  );
}

function layoutRects(
  layout: EngineLayoutState,
  paneIds: readonly PaneId[],
): Record<PaneId, WorldRect> {
  const rects: Record<PaneId, WorldRect> = {};
  for (const paneId of paneIds) {
    const node = layout.nodes[paneId];
    if (!node) throw new Error(`expected ${paneId} in layout`);
    rects[paneId] = node.rect;
  }
  return rects;
}

function pickRects(
  rects: Record<PaneId, WorldRect>,
  paneIds: readonly PaneId[],
): Record<PaneId, WorldRect> {
  const picked: Record<PaneId, WorldRect> = {};
  for (const paneId of paneIds) {
    const rect = rects[paneId];
    if (!rect) throw new Error(`expected ${paneId} in rects`);
    picked[paneId] = rect;
  }
  return picked;
}

function rectFor(layout: EngineLayoutState, paneId: PaneId): WorldRect {
  const node = layout.nodes[paneId];
  if (!node) throw new Error(`expected ${paneId} in layout`);
  return node.rect;
}

describe("planExpandLayout", () => {
  it("composes the hero split with grid-overflow remainder output", () => {
    const split = splitExpandColumns(BOUNDS);
    const strategy = resolveLayout(EXPAND_REMAINDER_STRATEGY_ID);
    const remainder = strategy.plan(
      { paneIds: REMAINDER_IDS, viewport: split.remainder },
      strategy.defaults,
    );
    const planned = planExpandLayout({
      paneIds: PANE_IDS,
      expandedPaneId: HERO_ID,
      viewport: BOUNDS,
    });

    const expectedRemainderRects = translateRects(remainder.rects, split.remainder);
    const expectedRemainderFrame = translateRect(
      remainder.frame ?? {
        x: 0,
        y: 0,
        width: split.remainder.width,
        height: split.remainder.height,
      },
      split.remainder,
    );
    expect(planned.rects[HERO_ID]).toEqual(split.hero);
    expect(pickRects(planned.rects, REMAINDER_IDS)).toEqual(expectedRemainderRects);
    expect(planned.frame).toEqual(composeExpandFrame(split.hero, expectedRemainderFrame, BOUNDS));
  });
});

describe("planLayout expand composition", () => {
  it("uses planExpandLayout instead of the retired expand bypass", () => {
    const expected = planExpandLayout({
      paneIds: PANE_IDS,
      expandedPaneId: HERO_ID,
      viewport: BOUNDS,
    });
    const activeStrategy = resolveLayout("single-row");
    const planned = planLayout(
      layoutWithPanes(PANE_IDS),
      BOUNDS,
      activeStrategy.id,
      activeStrategy.defaults,
      true,
      HERO_ID,
    );

    expect(layoutRects(planned, PANE_IDS)).toEqual(expected.rects);
    expect(planned.viewport).toEqual(expected.camera);
  });
});

describe("canvasLabStore expand composition", () => {
  beforeEach(() => {
    localStorage.clear();
    resetCanvasLabStoreForTests();
  });

  afterEach(() => {
    resetCanvasLabStoreForTests();
  });

  it("reflows through expandPane and unexpand toggles", () => {
    store().addPane();
    store().addPane();
    store().addPane();
    const organizedRect = rectFor(store().layout, "lab-1");

    store().expandPane("lab-1");

    const expandedRect = rectFor(store().layout, "lab-1");
    expect(store().expandedPaneId).toBe("lab-1");
    expect(expandedRect).toEqual(
      planExpandLayout({
        paneIds: ["lab-1", "lab-2", "lab-3"],
        expandedPaneId: "lab-1",
        viewport: store().bounds,
      }).rects["lab-1"],
    );
    expect(expandedRect).not.toEqual(organizedRect);

    store().unexpand();

    expect(store().expandedPaneId).toBeNull();
    expect(rectFor(store().layout, "lab-1")).not.toEqual(expandedRect);
  });
});
