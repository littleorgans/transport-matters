import { beforeEach, describe, expect, it, vi } from "vitest";
import { resolveLayout } from "../../engine/layout";
import { FRONTEND_STORAGE_KEYS } from "../../stores/persistence";
import { resetCapturedRunStoreForTests, useCapturedRunStore } from "../model/capturedRunStore";
import { titleForRef } from "../viewers/registry";
import { resetCanvasLabStoreForTests, useCanvasLabStore } from "./canvasLabStore";
import { CANVAS_LAB_STORAGE_VERSION } from "./canvasLabStore.persistence";
import { capturedPaneIds } from "./canvasLabStore.testSupport";

const { createCapturedRunMock, terminateRunMock } = vi.hoisted(() => ({
  createCapturedRunMock: vi.fn(),
  terminateRunMock: vi.fn(),
}));
vi.mock("@tm/core", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@tm/core")>()),
  createCapturedRun: createCapturedRunMock,
  terminateRun: terminateRunMock,
}));

const store = useCanvasLabStore.getState;
const LAB_WORKTREE_ID = "wt-lab";

function resetLabWithWorktree(): void {
  resetCanvasLabStoreForTests();
  store().setDefaultWorktree("space-lab", LAB_WORKTREE_ID);
}

function labelOf(paneId: string): string | undefined {
  const ref = store().contentRefs[paneId];
  if (!ref) return undefined;
  return "label" in ref ? ref.label : undefined;
}

function titleOf(paneId: string): string {
  const ref = store().contentRefs[paneId];
  if (!ref) throw new Error(`expected a content ref for ${paneId}`);
  return titleForRef(ref);
}

// Simulate a browser reload: a fresh page re-reads the persisted payloads into a brand-new in-memory
// store. Snapshot what is persisted, drop in-memory state (the reset's own persist write would clobber
// storage, so restore the snapshot afterwards), then rehydrate both stores from storage — exactly the
// page-load path. Captured-run bindings (runId/minimized) compose from their own persisted store.
async function reloadLab(): Promise<void> {
  const labRaw = localStorage.getItem(FRONTEND_STORAGE_KEYS.canvasLabStore);
  const capturedRaw = localStorage.getItem(FRONTEND_STORAGE_KEYS.capturedRunStore);
  resetCanvasLabStoreForTests();
  resetCapturedRunStoreForTests();
  if (labRaw !== null) localStorage.setItem(FRONTEND_STORAGE_KEYS.canvasLabStore, labRaw);
  if (capturedRaw !== null)
    localStorage.setItem(FRONTEND_STORAGE_KEYS.capturedRunStore, capturedRaw);
  await useCapturedRunStore.persist.rehydrate();
  await useCanvasLabStore.persist.rehydrate();
}

describe("canvasLabStore persistence adapter", () => {
  beforeEach(() => {
    localStorage.clear();
    resetLabWithWorktree();
    resetCapturedRunStoreForTests();
    createCapturedRunMock.mockReset();
    terminateRunMock.mockReset();
  });

  it("keeps pane titles identical across a reload, including the incremental index", async () => {
    store().addTerminal(); // Terminal-1
    store().addCapturedRun("claude"); // Claude-1
    const capturedId = capturedPaneIds(store().contentRefs)[0];
    if (!capturedId) throw new Error("expected a captured pane");
    const beforeTerminal = titleOf("lab-1");
    const beforeCaptured = titleOf(capturedId);
    expect(beforeTerminal).toBe("Terminal-1");
    expect(beforeCaptured).toBe("Claude-1");

    await reloadLab();

    // Bug2: today a reloaded captured pane drops its label and the title falls back to "Claude".
    expect(titleOf("lab-1")).toBe(beforeTerminal);
    expect(titleOf(capturedId)).toBe(beforeCaptured);
  });

  it("continues the per-prefix counter after a reload (Claude-3, not a restart)", async () => {
    store().addCapturedRun("claude"); // Claude-1
    store().addCapturedRun("claude"); // Claude-2

    await reloadLab();
    store().setDefaultWorktree("space-lab", LAB_WORKTREE_ID);
    store().addCapturedRun("claude"); // must be Claude-3, counter survived the reload

    const labels = capturedPaneIds(store().contentRefs)
      .map((id) => labelOf(id))
      .sort();
    expect(labels).toEqual(["Claude-1", "Claude-2", "Claude-3"]);
  });

  it("re-attaches a captured pane by its persisted runId without re-spawning", async () => {
    store().addCapturedRun("claude");
    const capturedId = capturedPaneIds(store().contentRefs)[0];
    if (!capturedId) throw new Error("expected a captured pane");
    useCapturedRunStore.setState({
      runs: { [capturedId]: { provider: "claude", runId: "run-1" } },
    });

    await reloadLab();

    // The runId binding survives the reload (kept in capturedRunStore), and the restored pane's ref
    // points at the same runKey, so the viewer's ensureRun re-attaches by id instead of POSTing anew.
    expect(useCapturedRunStore.getState().runs[capturedId]).toEqual({
      provider: "claude",
      runId: "run-1",
    });
    expect(store().contentRefs[capturedId]).toMatchObject({ runKey: capturedId });
    expect(createCapturedRunMock).not.toHaveBeenCalled();
  });

  it("keeps a minimized captured pane docked across a reload (S2 preserved)", async () => {
    store().addCapturedRun("claude");
    const capturedId = capturedPaneIds(store().contentRefs)[0];
    if (!capturedId) throw new Error("expected a captured pane");
    useCapturedRunStore.setState({
      runs: { [capturedId]: { provider: "claude", runId: "run-1" } },
    });
    vi.useFakeTimers();
    try {
      store().minimizePane(capturedId);
      vi.runAllTimers();
      expect(store().docked.map((entry) => entry.paneId)).toEqual([capturedId]);
    } finally {
      vi.useRealTimers();
    }

    await reloadLab();

    // Docked on reload, not reopened on the canvas; the run stays flagged minimized (S2).
    expect(store().layout.nodes[capturedId]).toBeUndefined();
    expect(store().docked.map((entry) => entry.paneId)).toEqual([capturedId]);
    expect(useCapturedRunStore.getState().runs[capturedId]?.minimized).toBe(true);
  });

  it("restores a docked pane after a reload", async () => {
    vi.useFakeTimers();
    try {
      store().addTerminal(); // lab-1 (Terminal-1)
      store().addPane(); // lab-2 (regular/demo, null ref)
      store().minimizePane("lab-1");
      store().minimizePane("lab-2");
      vi.runAllTimers();
      expect(
        store()
          .docked.map((entry) => entry.paneId)
          .sort(),
      ).toEqual(["lab-1", "lab-2"]);
    } finally {
      vi.useRealTimers();
    }

    await reloadLab();

    expect(
      store()
        .docked.map((entry) => entry.paneId)
        .sort(),
    ).toEqual(["lab-1", "lab-2"]);
    expect(store().layout.nodes["lab-1"]).toBeUndefined();
    expect(store().layout.nodes["lab-2"]).toBeUndefined();

    store().restorePane("lab-1");

    const restoredNode = store().layout.nodes["lab-1"];
    expect(restoredNode?.rect.width).toBeGreaterThan(0);
    expect(restoredNode?.rect.height).toBeGreaterThan(0);
    expect(store().contentRefs["lab-1"]).toEqual({
      kind: "terminal",
      owner: "local",
      label: "Terminal-1",
      worktreeId: LAB_WORKTREE_ID,
    });
    expect(store().docked.map((entry) => entry.paneId)).toEqual(["lab-2"]);
  });

  it("restores view controls across a reload without re-planning pane rects", async () => {
    const manualRect = { x: 123, y: 456, width: 321, height: 234 };
    store().addPane();
    store().addPane();
    store().setStrategy("single-row");
    store().setParam("minW", 420);
    store().setParam("gap", 8);
    store().setFitToContent(false);
    store().updatePaneRect("lab-1", manualRect);

    await reloadLab();

    expect(store().activeStrategyId).toBe("single-row");
    expect(store().params).toEqual({ minW: 420, gap: 8, margin: 64 });
    expect(store().fitToContent).toBe(false);
    expect(store().layout.nodes["lab-1"]?.rect).toEqual(manualRect);
  });

  it("restores expandedPaneId across a reload when the open set still permits it", async () => {
    store().addPane();
    store().addPane();
    store().setStrategy("single-row");
    store().setParam("minW", 420);
    store().setParam("gap", 8);
    store().expandPane("lab-1");
    const expandedRect = store().layout.nodes["lab-1"]?.rect;

    await reloadLab();

    expect(store().expandedPaneId).toBe("lab-1");
    expect(store().layout.nodes["lab-1"]?.rect).toEqual(expandedRect);

    const activeStrategyRects = resolveLayout(store().activeStrategyId).plan(
      { paneIds: ["lab-1", "lab-2"], viewport: store().bounds },
      store().params,
    ).rects;
    expect(store().layout.nodes["lab-1"]?.rect).not.toEqual(activeStrategyRects["lab-1"]);

    store().unexpand();

    expect(store().expandedPaneId).toBeNull();
    expect(store().layout.nodes["lab-1"]?.rect).toEqual(activeStrategyRects["lab-1"]);
    expect(store().layout.nodes["lab-2"]?.rect).toEqual(activeStrategyRects["lab-2"]);
  });

  it("loads clean when only a pre-S3 capturedRunStore is persisted (no lab-store key yet)", async () => {
    // A user upgrading to S3 has a persisted capturedRunStore but NO lab-store key (it never existed).
    // Both stores must hydrate without crashing or wiping: the runs survive, the lab starts empty.
    localStorage.clear();
    resetCanvasLabStoreForTests();
    resetCapturedRunStoreForTests();
    localStorage.removeItem(FRONTEND_STORAGE_KEYS.canvasLabStore);
    localStorage.setItem(
      FRONTEND_STORAGE_KEYS.capturedRunStore,
      JSON.stringify({
        version: 3,
        state: { runs: { "claude:k1": { provider: "claude", runId: "run-1" } } },
      }),
    );

    await useCapturedRunStore.persist.rehydrate();
    await useCanvasLabStore.persist.rehydrate();

    expect(useCapturedRunStore.getState().runs["claude:k1"]).toEqual({
      provider: "claude",
      runId: "run-1",
    });
    expect(Object.keys(store().layout.nodes)).toEqual([]);
    expect(store().docked).toEqual([]);
  });

  it("folds lab counters into a rehydrated core pane payload", async () => {
    localStorage.clear();
    resetCanvasLabStoreForTests();
    localStorage.setItem(
      FRONTEND_STORAGE_KEYS.canvasLabStore,
      JSON.stringify({
        version: CANVAS_LAB_STORAGE_VERSION,
        state: {
          contentRefs: {
            "lab-1": {
              kind: "terminal",
              owner: "local",
              label: "Terminal-1",
              worktreeId: LAB_WORKTREE_ID,
            },
          },
          paneRects: {
            "lab-1": { x: 0, y: 0, width: 360, height: 280 },
            "lab-2": { x: 400, y: 0, width: 360, height: 280 },
          },
          docked: [],
          paneCounters: { Terminal: 1 },
          nextPaneIndex: 2,
        },
      }),
    );

    await useCanvasLabStore.persist.rehydrate();

    expect(Object.keys(store().layout.nodes).sort()).toEqual(["lab-1", "lab-2"]);
    expect(store().contentRefs["lab-1"]).toEqual({
      kind: "terminal",
      owner: "local",
      label: "Terminal-1",
      worktreeId: LAB_WORKTREE_ID,
    });
    expect(store().contentRefs["lab-2"]).toBeUndefined();
    expect(store().nextPaneIndex).toBe(2);
  });
});
