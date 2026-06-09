import { beforeEach, describe, expect, it, vi } from "vitest";
import { FRONTEND_STORAGE_KEYS } from "../../stores/persistence";
import { titleForRef } from "../viewers/registry";
import { resetCanvasLabStoreForTests, useCanvasLabStore } from "./canvasLabStore";
import { capturedPaneIds } from "./canvasLabStore.testSupport";
import { resetCapturedRunStoreForTests, useCapturedRunStore } from "./capturedRunStore";
// Register the captured-run lifecycle hook (onMinimize/onRestore/onClose) the same way production does
// (via CanvasLabRoute's side-effect import), so minimize-docks and reload-attach ride the real wiring.
import "./labLifecycle";

const { createCapturedRunMock, deleteRunMock } = vi.hoisted(() => ({
  createCapturedRunMock: vi.fn(),
  deleteRunMock: vi.fn(),
}));
vi.mock("../../api", () => ({
  createCapturedRun: createCapturedRunMock,
  deleteRun: deleteRunMock,
}));

const store = useCanvasLabStore.getState;

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

describe("canvasLabStore reload persistence (S3 converge)", () => {
  beforeEach(() => {
    localStorage.clear();
    resetCanvasLabStoreForTests();
    resetCapturedRunStoreForTests();
    createCapturedRunMock.mockReset();
    deleteRunMock.mockReset();
  });

  it("restores all three pane kinds (regular + terminal + captured) on reload", async () => {
    store().addPane(); // lab-1 (regular/demo, no ref)
    store().addTerminal(); // lab-2 (Terminal-1)
    store().addCapturedRun("claude"); // claude:<uuid> (Claude-1)
    const capturedId = capturedPaneIds(store().contentRefs)[0];
    if (!capturedId) throw new Error("expected a captured pane");
    // The captured pane's run resolves (the viewer's ensureRun) before reload, so its binding persists.
    useCapturedRunStore.setState({
      runs: { [capturedId]: { provider: "claude", runId: "run-1" } },
    });

    await reloadLab();

    // All three panes are back on the canvas (bug1: today only the captured pane survived a reload).
    expect(store().layout.nodes["lab-1"]).toBeDefined();
    expect(store().layout.nodes["lab-2"]).toBeDefined();
    expect(store().layout.nodes[capturedId]).toBeDefined();
    // The regular pane carries no content ref; the terminal and captured panes carry theirs.
    expect(store().contentRefs["lab-1"]).toBeUndefined();
    expect(store().contentRefs["lab-2"]).toEqual({
      kind: "terminal",
      owner: "local",
      label: "Terminal-1",
    });
    expect(store().contentRefs[capturedId]).toEqual({
      kind: "captured-run",
      owner: "local",
      provider: "claude",
      runKey: capturedId,
      label: "Claude-1",
    });
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

  it("round-trips a docked terminal AND a docked regular pane across a reload (all kinds)", async () => {
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

    // Both non-captured docked panes come back IN THE DOCK (count correct), not on the canvas and not
    // lost — today they vanish because non-captured docked state lived only in the unpersisted store.
    expect(
      store()
        .docked.map((entry) => entry.paneId)
        .sort(),
    ).toEqual(["lab-1", "lab-2"]);
    expect(store().layout.nodes["lab-1"]).toBeUndefined();
    expect(store().layout.nodes["lab-2"]).toBeUndefined();
    // The docked terminal keeps its labelled ref; the regular pane docks with a null ref.
    const terminalEntry = store().docked.find((entry) => entry.paneId === "lab-1");
    const regularEntry = store().docked.find((entry) => entry.paneId === "lab-2");
    expect(terminalEntry?.ref).toEqual({ kind: "terminal", owner: "local", label: "Terminal-1" });
    expect(regularEntry?.ref).toBeNull();

    // Restore still works after a reload: the pane returns to the canvas and leaves the dock.
    store().restorePane("lab-1");
    expect(store().layout.nodes["lab-1"]).toBeDefined();
    expect(store().docked.map((entry) => entry.paneId)).toEqual(["lab-2"]);
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

  it("rehydrates a persisted lab-store payload into open canvas panes", async () => {
    localStorage.clear();
    resetCanvasLabStoreForTests();
    localStorage.setItem(
      FRONTEND_STORAGE_KEYS.canvasLabStore,
      JSON.stringify({
        version: 1,
        state: {
          contentRefs: { "lab-1": { kind: "terminal", owner: "local", label: "Terminal-1" } },
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
    });
    expect(store().contentRefs["lab-2"]).toBeUndefined();
    expect(store().nextPaneIndex).toBe(2);
  });
});
