import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PaneId, WorldRect } from "../../engine";
import { resolveLayout } from "../../engine/layout";
import { FRONTEND_STORAGE_KEYS } from "../../stores/persistence";
import { makeSessionSummary } from "../testUtils";
import { resetCanvasStoreForTests, useCanvasStore } from "./canvasStore";
import { CANVAS_STORE_STORAGE_VERSION } from "./canvasStore.persistence";

type CanvasStoreSnapshot = ReturnType<typeof useCanvasStore.getState>;

const store = useCanvasStore.getState;

function openPaneIds(state: CanvasStoreSnapshot): PaneId[] {
  return Object.values(state.layout.nodes)
    .filter((node) => node.lifecycle === "open")
    .map((node) => node.paneId);
}

async function reloadCanvas(): Promise<void> {
  const canvasRaw = localStorage.getItem(FRONTEND_STORAGE_KEYS.canvasStore);
  resetCanvasStoreForTests();
  localStorage.removeItem(FRONTEND_STORAGE_KEYS.canvasStore);
  if (canvasRaw !== null) localStorage.setItem(FRONTEND_STORAGE_KEYS.canvasStore, canvasRaw);
  await useCanvasStore.persist.rehydrate();
}

function writeCanvasStorage(state: unknown, version = CANVAS_STORE_STORAGE_VERSION): void {
  localStorage.setItem(
    FRONTEND_STORAGE_KEYS.canvasStore,
    JSON.stringify({
      version,
      state,
    }),
  );
}

function spawnTranscript(sessionId: string, title: string): PaneId {
  store().spawnOrFocusTranscript(makeSessionSummary({ sessionId: sessionId, title }));
  return `transcript:${sessionId}`;
}

function spawnResource(sessionId: string, resourceId: string): PaneId {
  return store().spawnPane({
    kind: "resource",
    owner: "local",
    sessionId,
    resourceId,
  });
}

describe("canvasStore persistence adapter", () => {
  beforeEach(() => {
    localStorage.clear();
    resetCanvasStoreForTests();
    localStorage.clear();
  });

  it("round-trips panes, dock, and view state without re-planning rects", async () => {
    vi.useFakeTimers();
    try {
      const transcriptId = spawnTranscript("alpha", "Alpha session");
      const resourceId = spawnResource("alpha", "resource-1");
      store().minimizePane(resourceId);
      vi.runAllTimers();

      const manualRect: WorldRect = { x: 123, y: 456, width: 321, height: 234 };
      useCanvasStore.setState({
        activeStrategyId: "single-row",
        params: { minW: 420, gap: 8, margin: 64 },
        fitToContent: false,
      });
      store().movePane(transcriptId, manualRect);

      await reloadCanvas();

      const reloaded = store();
      expect(reloaded.activeStrategyId).toBe("single-row");
      expect(reloaded.params).toEqual({ minW: 420, gap: 8, margin: 64 });
      expect(reloaded.fitToContent).toBe(false);
      expect(reloaded.layout.nodes[transcriptId]?.rect).toEqual(manualRect);
      expect(reloaded.layout.nodes[resourceId]).toBeUndefined();
      expect(reloaded.docked.map((entry) => entry.paneId)).toEqual([resourceId]);
      expect(reloaded.docked[0]?.record?.contentRef).toEqual({
        kind: "resource",
        owner: "local",
        sessionId: "alpha",
        resourceId: "resource-1",
      });
      expect(Object.keys(reloaded.panes).sort()).toEqual(["session-picker", transcriptId].sort());
    } finally {
      vi.useRealTimers();
    }
  });

  it("restores expandedPaneId only when the rebuilt open set permits it", async () => {
    const transcriptId = spawnTranscript("alpha", "Alpha session");
    spawnResource("alpha", "resource-1");
    store().expandPane(transcriptId);
    const expandedRect = store().layout.nodes[transcriptId]?.rect;

    await reloadCanvas();

    const reloaded = store();
    expect(reloaded.expandedPaneId).toBe(transcriptId);
    expect(reloaded.layout.nodes[transcriptId]?.rect).toEqual(expandedRect);

    const activeStrategyRects = resolveLayout(reloaded.activeStrategyId).plan(
      { paneIds: openPaneIds(reloaded), viewport: reloaded.bounds },
      reloaded.params,
    ).rects;
    expect(reloaded.layout.nodes[transcriptId]?.rect).not.toEqual(
      activeStrategyRects[transcriptId],
    );

    writeCanvasStorage({
      contentRefs: {
        [transcriptId]: { kind: "session-timeline", owner: "local", sessionId: "alpha" },
      },
      paneRects: {
        [transcriptId]: { x: 0, y: 0, width: 360, height: 280 },
      },
      docked: [],
      activeStrategyId: "grid-fit",
      params: {},
      fitToContent: true,
      expandedPaneId: transcriptId,
    });

    await reloadCanvas();

    expect(store().expandedPaneId).toBeNull();
    expect(Object.keys(store().layout.nodes)).toEqual([transcriptId]);
  });

  it("leaves a fresh profile untouched when no persisted payload exists", async () => {
    localStorage.removeItem(FRONTEND_STORAGE_KEYS.canvasStore);

    await useCanvasStore.persist.rehydrate();

    expect(Object.keys(store().panes)).toEqual(["session-picker"]);
    expect(Object.keys(store().layout.nodes)).toEqual(["session-picker"]);
    expect(store().docked).toEqual([]);
  });

  it("resets stale payloads cleanly instead of hydrating invalid refs", async () => {
    resetCanvasStoreForTests();
    writeCanvasStorage({
      contentRefs: {
        "transcript:legacy": { kind: "session", owner: "local", sessionId: "legacy" },
      },
      paneRects: {
        "transcript:legacy": { x: 0, y: 0, width: 360, height: 280 },
      },
      docked: [],
      activeStrategyId: "grid-fit",
      params: {},
      fitToContent: true,
      expandedPaneId: null,
    });

    await useCanvasStore.persist.rehydrate();

    expect(store().panes).toEqual({});
    expect(store().layout.nodes).toEqual({});
    expect(store().layout.focusedPaneId).toBeNull();
    expect(store().docked).toEqual([]);
  });
});
