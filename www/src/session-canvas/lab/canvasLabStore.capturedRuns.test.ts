import { beforeEach, describe, expect, it, vi } from "vitest";
import { resetCapturedRunStoreForTests, useCapturedRunStore } from "../model/capturedRunStore";
import { resetCanvasLabStoreForTests, useCanvasLabStore } from "./canvasLabStore";
import { capturedPaneIds } from "./canvasLabStore.testSupport";

const { createCapturedRunMock, terminateRunMock } = vi.hoisted(() => ({
  createCapturedRunMock: vi.fn(),
  terminateRunMock: vi.fn(),
}));
vi.mock("../../api", () => ({
  createCapturedRun: createCapturedRunMock,
  terminateRun: terminateRunMock,
}));

const store = useCanvasLabStore.getState;
const LAB_WORKTREE_ID = "wt-lab";

function resetLabWithWorktree(): void {
  resetCanvasLabStoreForTests();
  store().setDefaultWorktree("space-lab", LAB_WORKTREE_ID);
}

describe("canvasLabStore captured runs", () => {
  beforeEach(() => {
    localStorage.clear();
    resetLabWithWorktree();
    resetCapturedRunStoreForTests();
    createCapturedRunMock.mockReset();
    terminateRunMock.mockReset();
  });

  it("spawns an independent pane and key per Spawn, even for the same provider", () => {
    store().addCapturedRun("claude");
    store().addCapturedRun("claude");

    const ids = capturedPaneIds(store().contentRefs);
    expect(ids).toHaveLength(2);
    // Distinct pane ids => distinct run keys => the two panes own independent runs.
    expect(ids[0]).not.toBe(ids[1]);
    for (const id of ids) expect(id.startsWith("claude:")).toBe(true);
  });

  it("refuses spawnable panes when no rooted worktree is available", () => {
    resetCanvasLabStoreForTests();

    expect(() => store().addCapturedRun("claude")).toThrow(/rooted worktree/i);
    expect(() => store().addTerminal()).toThrow(/rooted worktree/i);

    expect(capturedPaneIds(store().contentRefs)).toEqual([]);
    expect(store().contentRefs).toEqual({});
  });

  it("minimizePane docks a captured pane and keeps its run alive (no stop)", () => {
    vi.useFakeTimers();
    try {
      terminateRunMock.mockResolvedValue(undefined);
      store().addCapturedRun("claude");
      const paneId = capturedPaneIds(store().contentRefs)[0];
      if (!paneId) throw new Error("expected a captured pane");
      useCapturedRunStore.setState({ runs: { [paneId]: { provider: "claude", runId: "run-1" } } });

      store().minimizePane(paneId);
      vi.runAllTimers();

      // Minimize is non-destructive: the run is NOT terminated, and its binding is KEPT so restore
      // re-attaches by id (the WS close on unmount only drops the viewer count). The captured-run
      // onMinimize hook also flags the persisted record minimized so a reload docks it (S2).
      expect(terminateRunMock).not.toHaveBeenCalled();
      expect(useCapturedRunStore.getState().runs[paneId]).toEqual({
        provider: "claude",
        runId: "run-1",
        minimized: true,
      });
      // The pane leaves the canvas and parks in the dock for local restore.
      expect(store().contentRefs[paneId]).toBeUndefined();
      expect(store().layout.nodes[paneId]).toBeUndefined();
      expect(store().docked.map((docked) => docked.paneId)).toEqual([paneId]);
      expect(store().docked[0]?.ref).toEqual({
        kind: "captured-run",
        owner: "local",
        provider: "claude",
        runKey: paneId,
        label: "Claude-1",
        worktreeId: LAB_WORKTREE_ID,
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it("restorePaneAtIndex restores the docked pane into the order slot the drop chose", () => {
    vi.useFakeTimers();
    try {
      resetLabWithWorktree();
      store().addTerminal(); // lab-1
      store().addTerminal(); // lab-2
      store().addTerminal(); // lab-3
      store().minimizePane("lab-2");
      vi.runAllTimers();
      expect(store().docked.map((docked) => docked.paneId)).toEqual(["lab-2"]);

      store().restorePaneAtIndex("lab-2", 0);

      expect(store().docked).toEqual([]);
      expect(store().layout.order).toEqual(["lab-2", "lab-1", "lab-3"]);
      expect(store().layout.nodes["lab-2"]?.lifecycle).toBe("open");
    } finally {
      vi.useRealTimers();
    }
  });

  it("restorePaneAtIndex clamps an out-of-range index to the tail", () => {
    vi.useFakeTimers();
    try {
      resetLabWithWorktree();
      store().addTerminal(); // lab-1
      store().addTerminal(); // lab-2
      store().minimizePane("lab-1");
      vi.runAllTimers();

      store().restorePaneAtIndex("lab-1", 99);

      expect(store().layout.order).toEqual(["lab-2", "lab-1"]);
      expect(store().docked).toEqual([]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("restorePane re-seeds a docked captured pane without spawning a new run", () => {
    vi.useFakeTimers();
    try {
      terminateRunMock.mockResolvedValue(undefined);
      store().addCapturedRun("claude");
      const paneId = capturedPaneIds(store().contentRefs)[0];
      if (!paneId) throw new Error("expected a captured pane");
      useCapturedRunStore.setState({ runs: { [paneId]: { provider: "claude", runId: "run-1" } } });
      store().minimizePane(paneId);
      vi.runAllTimers();
      createCapturedRunMock.mockClear();

      store().restorePane(paneId);

      // The pane is back on the canvas at its original id, off the dock; the kept binding lets the
      // viewer's ensureRun re-attach by id. restorePane itself never POSTs a new spawn.
      expect(store().contentRefs[paneId]).toEqual({
        kind: "captured-run",
        owner: "local",
        provider: "claude",
        runKey: paneId,
        label: "Claude-1",
        worktreeId: LAB_WORKTREE_ID,
      });
      expect(store().layout.nodes[paneId]).toBeDefined();
      expect(store().docked).toEqual([]);
      expect(createCapturedRunMock).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("restorePane clears the persisted minimized flag so a reload after restore reopens it", () => {
    vi.useFakeTimers();
    try {
      store().addCapturedRun("claude");
      const paneId = capturedPaneIds(store().contentRefs)[0];
      if (!paneId) throw new Error("expected a captured pane");
      useCapturedRunStore.setState({ runs: { [paneId]: { provider: "claude", runId: "run-1" } } });

      store().minimizePane(paneId);
      vi.runAllTimers();
      expect(useCapturedRunStore.getState().runs[paneId]?.minimized).toBe(true);

      store().restorePane(paneId);

      // Restore runs the captured-run onRestore hook through the seam (no kind=== branch), the inverse
      // of minimize: the flag clears so a later reload reopens the pane as active, not docked.
      expect(useCapturedRunStore.getState().runs[paneId]?.minimized).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it("closeDockedPane kills a docked captured run (POST /terminate) and drops the dock entry", () => {
    vi.useFakeTimers();
    try {
      terminateRunMock.mockResolvedValue(undefined);
      store().addCapturedRun("claude");
      const paneId = capturedPaneIds(store().contentRefs)[0];
      if (!paneId) throw new Error("expected a captured pane");
      useCapturedRunStore.setState({ runs: { [paneId]: { provider: "claude", runId: "run-1" } } });
      store().minimizePane(paneId);
      vi.runAllTimers();
      expect(store().docked.map((docked) => docked.paneId)).toEqual([paneId]);

      store().closeDockedPane(paneId);

      // Close from the dock runs the captured-run onClose hook: the run is terminated (POST /terminate) and the
      // entry leaves the dock. The pane never returns to the canvas.
      expect(terminateRunMock).toHaveBeenCalledWith("run-1");
      expect(useCapturedRunStore.getState().runs[paneId]).toBeUndefined();
      expect(store().docked).toEqual([]);
      expect(store().contentRefs[paneId]).toBeUndefined();
      expect(store().layout.nodes[paneId]).toBeUndefined();
    } finally {
      vi.useRealTimers();
    }
  });

  it("closeDockedPane drops a non-captured docked entry with no run side effect", () => {
    vi.useFakeTimers();
    try {
      store().addTerminal(); // lab-1 (terminal ref, no run)
      store().minimizePane("lab-1");
      vi.runAllTimers();
      expect(store().docked.map((docked) => docked.paneId)).toEqual(["lab-1"]);

      store().closeDockedPane("lab-1");

      expect(terminateRunMock).not.toHaveBeenCalled();
      expect(store().docked).toEqual([]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("minimizes and restores a non-captured pane (null ref) through the generic dock path", () => {
    vi.useFakeTimers();
    try {
      store().addTerminal(); // lab-1 (terminal ref)
      store().addPane(); // lab-2 (demo card/ruler, no content ref)

      store().minimizePane("lab-2");
      vi.runAllTimers();

      // A demo pane carries no ref: it docks by paneId with a null ref and re-creates on restore.
      expect(store().layout.nodes["lab-2"]).toBeUndefined();
      expect(store().docked.map((docked) => docked.paneId)).toEqual(["lab-2"]);
      expect(store().docked[0]?.ref).toBeNull();

      store().restorePane("lab-2");

      expect(store().layout.nodes["lab-2"]).toBeDefined();
      expect(store().docked).toEqual([]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("closePane ([X]) kills (stops) an established captured run and removes the pane", () => {
    vi.useFakeTimers();
    try {
      terminateRunMock.mockResolvedValue(undefined);
      store().addCapturedRun("claude");
      const paneId = capturedPaneIds(store().contentRefs)[0];
      if (!paneId) throw new Error("expected a captured pane");
      useCapturedRunStore.setState({ runs: { [paneId]: { provider: "claude", runId: "run-1" } } });

      store().closePane(paneId);
      vi.runAllTimers();

      // Close is destructive: the run is terminated (POST /terminate) so it leaves the director too.
      expect(terminateRunMock).toHaveBeenCalledWith("run-1");
      expect(useCapturedRunStore.getState().runs[paneId]).toBeUndefined();
      expect(store().contentRefs[paneId]).toBeUndefined();
    } finally {
      vi.useRealTimers();
    }
  });

  it("leaves captured runs untouched when a non-captured pane is closed", () => {
    vi.useFakeTimers();
    try {
      useCapturedRunStore.setState({
        runs: { "claude:k1": { provider: "claude", runId: "run-1" } },
      });
      store().addTerminal(); // lab-1 (bare terminal, not a captured run)

      store().closePane("lab-1");
      vi.runAllTimers();

      expect(terminateRunMock).not.toHaveBeenCalled();
      expect(useCapturedRunStore.getState().runs["claude:k1"]).toEqual({
        provider: "claude",
        runId: "run-1",
      });
    } finally {
      vi.useRealTimers();
    }
  });
});
