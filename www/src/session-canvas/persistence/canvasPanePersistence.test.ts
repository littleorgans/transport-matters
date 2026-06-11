import { describe, expect, it } from "vitest";
import { createInitialEngineLayoutState, markNodeClosing, type PaneId } from "../../engine";
import { seedParams } from "../../engine/layout";
import type { DockedPane, PaneContentRef } from "../model/paneRecords";
import {
  collectOpenPaneRects,
  type PersistedCanvasPanes,
  type PersistedCanvasState,
  rebuildPersistedCanvasState,
  rebuildPersistedPanes,
  seedPaneFromRecord,
} from "./canvasPanePersistence";

const terminalRef = {
  kind: "terminal",
  owner: "local",
  label: "Terminal-1",
} satisfies PaneContentRef;

const capturedRef = {
  kind: "captured-run",
  owner: "local",
  provider: "claude",
  runKey: "claude:k1",
  label: "Claude-1",
} satisfies PaneContentRef;

function emptySeedState() {
  return {
    contentRefs: {},
    layout: createInitialEngineLayoutState(),
  };
}

function seededSeedState() {
  let seeded = seedPaneFromRecord(emptySeedState(), "lab-1", null, {
    x: 0,
    y: 0,
    width: 360,
    height: 280,
  });
  seeded = seedPaneFromRecord(seeded, "lab-2", terminalRef, {
    x: 400,
    y: 0,
    width: 360,
    height: 280,
  });
  return seeded;
}

function emptySeedCanvasState() {
  return {
    ...emptySeedState(),
    activeStrategyId: "grid-fit",
    params: seedParams("grid-fit"),
    fitToContent: true,
    expandedPaneId: null,
  };
}

function seededSeedCanvasState() {
  return {
    ...seededSeedState(),
    activeStrategyId: "single-row",
    params: seedParams("single-row"),
    fitToContent: false,
    expandedPaneId: "lab-1",
  };
}

describe("canvas pane persistence", () => {
  it("preserves current seeded panes when no persisted payload exists", () => {
    const current = seededSeedState();

    for (const payload of [undefined, {}]) {
      const rebuilt = rebuildPersistedPanes(payload, current);

      expect(rebuilt.layout).toBe(current.layout);
      expect(rebuilt.contentRefs).toBe(current.contentRefs);
      expect(Object.keys(rebuilt.layout.nodes).sort()).toEqual(["lab-1", "lab-2"]);
      expect(rebuilt.docked).toEqual([]);
    }
  });

  it("hydrates a valid empty persisted pane payload as an empty canvas", () => {
    const current = seededSeedState();
    const rebuilt = rebuildPersistedPanes(
      {
        contentRefs: {},
        paneRects: {},
        docked: [],
      },
      current,
    );

    expect(rebuilt.layout).not.toBe(current.layout);
    expect(rebuilt.contentRefs).toEqual({});
    expect(rebuilt.layout.focusedPaneId).toBeNull();
    expect(rebuilt.layout.nodes).toEqual({});
    expect(rebuilt.docked).toEqual([]);
  });

  it("resets non-record and malformed pane payloads without throwing", () => {
    const current = seededSeedState();
    const malformedPayloads: unknown[] = [
      "bad-payload",
      [],
      {
        contentRefs: [],
        paneRects: {},
        docked: [],
      },
      {
        contentRefs: {},
        paneRects: [],
        docked: [],
      },
      {
        contentRefs: {},
        paneRects: {},
        docked: {},
      },
    ];

    for (const payload of malformedPayloads) {
      let rebuilt: ReturnType<typeof rebuildPersistedPanes> | undefined;

      expect(() => {
        rebuilt = rebuildPersistedPanes(payload, current);
      }).not.toThrow();

      expect(rebuilt?.contentRefs).toEqual({});
      expect(rebuilt?.layout.focusedPaneId).toBeNull();
      expect(rebuilt?.layout.nodes).toEqual({});
      expect(rebuilt?.docked).toEqual([]);
    }
  });

  it("preserves current canvas view state when no persisted payload exists", () => {
    const current = seededSeedCanvasState();
    const rebuilt = rebuildPersistedCanvasState({}, current);

    expect(rebuilt.layout).toBe(current.layout);
    expect(rebuilt.contentRefs).toBe(current.contentRefs);
    expect(rebuilt.activeStrategyId).toBe(current.activeStrategyId);
    expect(rebuilt.params).toBe(current.params);
    expect(rebuilt.fitToContent).toBe(false);
    expect(rebuilt.expandedPaneId).toBe("lab-1");
  });

  it("resets stale pane payloads instead of hydrating invalid refs", () => {
    const current = seededSeedState();
    const stalePayload: unknown = {
      contentRefs: { "lab-1": { kind: "session", owner: "local", sessionId: "legacy" } },
      paneRects: { "lab-1": { x: 0, y: 0, width: 360, height: 280 } },
      docked: [],
    };

    const rebuilt = rebuildPersistedPanes(stalePayload, current);

    expect(rebuilt.contentRefs).toEqual({});
    expect(rebuilt.layout.focusedPaneId).toBeNull();
    expect(rebuilt.layout.nodes).toEqual({});
    expect(rebuilt.docked).toEqual([]);
  });

  it("rebuilds open pane records for demo, terminal, and captured-run panes", () => {
    const persisted = {
      contentRefs: {
        "terminal-1": terminalRef,
        "claude:k1": capturedRef,
      },
      paneRects: {
        "demo-1": { x: 0, y: 0, width: 360, height: 280 },
        "terminal-1": { x: 400, y: 0, width: 360, height: 280 },
        "claude:k1": { x: 800, y: 0, width: 360, height: 280 },
      },
      docked: [],
    } satisfies PersistedCanvasPanes;

    const rebuilt = rebuildPersistedPanes(persisted, emptySeedState());

    expect(Object.keys(rebuilt.layout.nodes).sort()).toEqual(["claude:k1", "demo-1", "terminal-1"]);
    expect(rebuilt.layout.nodes["demo-1"]?.rect).toEqual(persisted.paneRects["demo-1"]);
    expect(rebuilt.layout.nodes["terminal-1"]?.rect).toEqual(persisted.paneRects["terminal-1"]);
    expect(rebuilt.layout.nodes["claude:k1"]?.rect).toEqual(persisted.paneRects["claude:k1"]);
    expect(rebuilt.contentRefs["demo-1"]).toBeUndefined();
    expect(rebuilt.contentRefs["terminal-1"]).toEqual(terminalRef);
    expect(rebuilt.contentRefs["claude:k1"]).toEqual(capturedRef);
  });

  it("restores docked records without reopening them on the canvas", () => {
    const docked = [
      { paneId: "demo-2", ref: null },
      { paneId: "terminal-2", ref: { ...terminalRef, label: "Terminal-2" } },
    ] satisfies DockedPane[];
    const persisted = {
      contentRefs: { "terminal-1": terminalRef },
      paneRects: { "terminal-1": { x: 0, y: 0, width: 360, height: 280 } },
      docked,
    } satisfies PersistedCanvasPanes;

    const rebuilt = rebuildPersistedPanes(persisted, emptySeedState());

    expect(Object.keys(rebuilt.layout.nodes)).toEqual(["terminal-1"]);
    expect(rebuilt.docked).toEqual(docked);
    expect(rebuilt.layout.nodes["demo-2"]).toBeUndefined();
    expect(rebuilt.layout.nodes["terminal-2"]).toBeUndefined();
  });

  it("rebuilds from a raw persisted payload", () => {
    const rawPayload: unknown = {
      contentRefs: { "terminal-1": terminalRef },
      paneRects: {
        "terminal-1": { x: 0, y: 0, width: 360, height: 280 },
        "demo-1": { x: 400, y: 0, width: 360, height: 280 },
      },
      docked: [],
    };

    const rebuilt = rebuildPersistedPanes(rawPayload, emptySeedState());

    expect(Object.keys(rebuilt.layout.nodes).sort()).toEqual(["demo-1", "terminal-1"]);
    expect(rebuilt.contentRefs["terminal-1"]).toEqual(terminalRef);
    expect(rebuilt.contentRefs["demo-1"]).toBeUndefined();
  });

  it("collects open pane rects and excludes panes mid-close", () => {
    const openPaneId: PaneId = "open-1";
    const closingPaneId: PaneId = "closing-1";
    let seeded = seedPaneFromRecord(emptySeedState(), openPaneId, terminalRef, {
      x: 0,
      y: 0,
      width: 360,
      height: 280,
    });
    seeded = seedPaneFromRecord(seeded, closingPaneId, capturedRef, {
      x: 400,
      y: 0,
      width: 360,
      height: 280,
    });

    const layout = markNodeClosing(seeded.layout, closingPaneId);

    expect(collectOpenPaneRects(layout)).toEqual({
      [openPaneId]: { x: 0, y: 0, width: 360, height: 280 },
    });
  });

  it("restores strategy, params, and fit controls without re-planning rects", () => {
    const manualRect = { x: 123, y: 456, width: 789, height: 321 };
    const persisted = {
      contentRefs: {},
      paneRects: {
        "demo-1": manualRect,
        "demo-2": { x: 900, y: 12, width: 333, height: 222 },
      },
      docked: [],
      activeStrategyId: "single-row",
      params: { minW: 420, gap: 8, margin: 12 },
      fitToContent: false,
      expandedPaneId: null,
    } satisfies PersistedCanvasState;

    const rebuilt = rebuildPersistedCanvasState(persisted, emptySeedCanvasState());

    expect(rebuilt.activeStrategyId).toBe("single-row");
    expect(rebuilt.params).toEqual({ minW: 420, gap: 8, margin: 12 });
    expect(rebuilt.fitToContent).toBe(false);
    expect(rebuilt.layout.nodes["demo-1"]?.rect).toEqual(manualRect);
  });

  it("sanitizes persisted params against the restored strategy", () => {
    const persisted: unknown = {
      contentRefs: {},
      paneRects: { "demo-1": { x: 0, y: 0, width: 360, height: 280 } },
      docked: [],
      activeStrategyId: "grid-fit",
      params: {
        minW: 999,
        gap: 32,
        minH: "bad",
        lastRow: "center",
        packing: "bogus",
        unknown: 1,
      },
      fitToContent: true,
      expandedPaneId: null,
    };

    const rebuilt = rebuildPersistedCanvasState(persisted, emptySeedCanvasState());

    expect(rebuilt.params.minW).toBe(640);
    expect(rebuilt.params.gap).toBe(32);
    expect(rebuilt.params.minH).toBe(seedParams("grid-fit").minH);
    expect(rebuilt.params.lastRow).toBe("center");
    expect(rebuilt.params.packing).toBe(seedParams("grid-fit").packing);
    expect("unknown" in rebuilt.params).toBe(false);
  });

  it("restores expandedPaneId only when the rebuilt open set permits it", () => {
    const base = {
      contentRefs: {},
      paneRects: {
        "demo-1": { x: 0, y: 0, width: 360, height: 280 },
        "demo-2": { x: 400, y: 0, width: 360, height: 280 },
      },
      docked: [{ paneId: "docked-1", ref: null }],
      activeStrategyId: "grid-fit",
      params: seedParams("grid-fit"),
      fitToContent: true,
    } satisfies Omit<PersistedCanvasState, "expandedPaneId">;

    expect(
      rebuildPersistedCanvasState({ ...base, expandedPaneId: "demo-1" }, emptySeedCanvasState())
        .expandedPaneId,
    ).toBe("demo-1");
    expect(
      rebuildPersistedCanvasState({ ...base, expandedPaneId: "docked-1" }, emptySeedCanvasState())
        .expandedPaneId,
    ).toBeNull();
    expect(
      rebuildPersistedCanvasState({ ...base, expandedPaneId: "missing-1" }, emptySeedCanvasState())
        .expandedPaneId,
    ).toBeNull();
    expect(
      rebuildPersistedCanvasState(
        {
          ...base,
          paneRects: { "demo-1": base.paneRects["demo-1"] },
          expandedPaneId: "demo-1",
        },
        emptySeedCanvasState(),
      ).expandedPaneId,
    ).toBeNull();
  });
});
