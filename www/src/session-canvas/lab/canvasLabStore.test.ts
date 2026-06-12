import { beforeEach, describe, expect, it, vi } from "vitest";
import { resolveLayout } from "../../engine/layout";
import {
  framedPaneId,
  resetCanvasLabStoreForTests,
  UNFRAME_FLY_PANE_LIMIT,
  useCanvasLabStore,
} from "./canvasLabStore";
import { capturedPaneIds } from "./canvasLabStore.testSupport";
import { resetCapturedRunStoreForTests, useCapturedRunStore } from "./capturedRunStore";
// Register the captured-run lifecycle hook (onClose -> stopRun) the same way production does (via
// CanvasLabRoute's side-effect import), so close-kills-run is exercised through the real wiring.
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

describe("canvasLabStore terminals", () => {
  // Each spawned terminal gets a monotonic per-type label (Terminal-1, Terminal-2, ...).
  const terminalRef = (n: number) =>
    ({ kind: "terminal", owner: "local", label: `Terminal-${n}` }) as const;

  it("spawns a pane that carries a terminal content ref", () => {
    resetCanvasLabStoreForTests();

    store().addTerminal();

    expect(store().contentRefs["lab-1"]).toEqual(terminalRef(1));
    expect(store().layout.nodes["lab-1"]).toBeDefined();
  });

  it("spawns multiple independent terminals alongside demo panes", () => {
    resetCanvasLabStoreForTests();

    store().addTerminal(); // lab-1 (Terminal-1)
    store().addPane(); // lab-2 (demo card/ruler, no content ref)
    store().addTerminal(); // lab-3 (Terminal-2)

    expect(store().contentRefs).toEqual({ "lab-1": terminalRef(1), "lab-3": terminalRef(2) });
    expect(Object.keys(store().layout.nodes).sort()).toEqual(["lab-1", "lab-2", "lab-3"]);
  });

  it("dockPane parks a ref in the dock without touching the layout", () => {
    resetCanvasLabStoreForTests();
    const ref = {
      kind: "resource",
      owner: "local",
      source: "path",
      path: "/t/x.png",
    } as const;
    const layoutBefore = store().layout;

    const paneId = store().dockPane(ref);

    expect(store().layout).toBe(layoutBefore);
    expect(store().contentRefs[paneId]).toBeUndefined();
    expect(store().docked[0]).toMatchObject({ paneId, ref });
  });

  it("commitReorder splices the order and replans", () => {
    resetCanvasLabStoreForTests();
    store().addTerminal();
    store().addTerminal();

    store().commitReorder("lab-2", 0);
    expect(store().layout.order).toEqual(["lab-2", "lab-1"]);
  });

  it("spawnPane opens a locator resource pane keyed by its registry pane id", () => {
    resetCanvasLabStoreForTests();
    const ref = {
      kind: "resource",
      owner: "local",
      source: "path",
      path: "/tmp/shot.png",
    } as const;

    const paneId = store().spawnPane(ref);

    expect(paneId).toBe("resource:path:/tmp/shot.png");
    expect(store().contentRefs[paneId]).toEqual(ref);
    expect(store().layout.nodes[paneId]).toBeDefined();
  });

  it("spawnPane dedupes to the existing pane and restores a docked one", () => {
    vi.useFakeTimers();
    try {
      resetCanvasLabStoreForTests();
      const ref = {
        kind: "resource",
        owner: "local",
        source: "path",
        path: "/tmp/shot.png",
      } as const;

      const paneId = store().spawnPane(ref);
      expect(store().spawnPane(ref)).toBe(paneId);
      expect(Object.keys(store().contentRefs)).toHaveLength(1);

      store().minimizePane(paneId);
      vi.runAllTimers();
      expect(store().layout.nodes[paneId]).toBeUndefined();
      expect(store().spawnPane(ref)).toBe(paneId);
      expect(store().docked).toHaveLength(0);
      expect(store().layout.nodes[paneId]?.lifecycle).toBe("open");
    } finally {
      vi.useRealTimers();
    }
  });

  it("forgets a pane's content ref once its close animation completes", () => {
    vi.useFakeTimers();
    try {
      resetCanvasLabStoreForTests();
      store().addTerminal(); // lab-1 (Terminal-1)
      store().addTerminal(); // lab-2 (Terminal-2)

      store().closePane("lab-1");
      vi.runAllTimers();

      expect(store().contentRefs).toEqual({ "lab-2": terminalRef(2) });
      expect(store().layout.nodes["lab-1"]).toBeUndefined();
    } finally {
      vi.useRealTimers();
    }
  });

  it("labels spawned panes incrementally per type, monotonic and never reused on close", () => {
    vi.useFakeTimers();
    try {
      resetCanvasLabStoreForTests();
      store().addTerminal(); // lab-1 Terminal-1
      store().addCapturedRun("claude"); // Claude-1
      store().addTerminal(); // lab-2 Terminal-2
      store().addCapturedRun("codex"); // Codex-1
      store().addCapturedRun("claude"); // Claude-2

      const labels = Object.values(store().contentRefs).map((ref) =>
        ref.kind === "terminal" || ref.kind === "captured-run" ? ref.label : undefined,
      );
      expect(labels).toEqual(
        expect.arrayContaining(["Terminal-1", "Terminal-2", "Claude-1", "Claude-2", "Codex-1"]),
      );

      // Closing a pane does not reset the counter: the next terminal is Terminal-3, not Terminal-1.
      store().closePane("lab-1");
      vi.runAllTimers();
      store().addTerminal(); // lab-3 Terminal-3
      const terminalLabels = Object.values(store().contentRefs)
        .filter((ref) => ref.kind === "terminal")
        .map((ref) => (ref.kind === "terminal" ? ref.label : ""));
      expect(terminalLabels).toContain("Terminal-3");
      expect(terminalLabels).not.toContain("Terminal-1"); // closed, never reused
    } finally {
      vi.useRealTimers();
    }
  });

  it("spawns captured-run panes carrying the chosen provider on their content ref", () => {
    resetCanvasLabStoreForTests();

    store().addCapturedRun("claude");
    store().addCapturedRun("codex");

    const captured = Object.values(store().contentRefs).filter(
      (ref) => ref.kind === "captured-run",
    );
    expect(captured).toHaveLength(2);
    expect(captured).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ kind: "captured-run", owner: "local", provider: "claude" }),
        expect.objectContaining({ kind: "captured-run", owner: "local", provider: "codex" }),
      ]),
    );
    // The run key rides on the ref and matches the pane id.
    for (const [paneId, ref] of Object.entries(store().contentRefs)) {
      if (ref.kind === "captured-run") expect(ref.runKey).toBe(paneId);
    }
  });
});

describe("canvasLabStore captured runs", () => {
  beforeEach(() => {
    localStorage.clear();
    resetCanvasLabStoreForTests();
    resetCapturedRunStoreForTests();
    createCapturedRunMock.mockReset();
    deleteRunMock.mockReset();
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

  it("minimizePane docks a captured pane and keeps its run alive (no stop)", () => {
    vi.useFakeTimers();
    try {
      deleteRunMock.mockResolvedValue(undefined);
      store().addCapturedRun("claude");
      const paneId = capturedPaneIds(store().contentRefs)[0];
      if (!paneId) throw new Error("expected a captured pane");
      useCapturedRunStore.setState({ runs: { [paneId]: { provider: "claude", runId: "run-1" } } });

      store().minimizePane(paneId);
      vi.runAllTimers();

      // Minimize is non-destructive: the run is NOT stopped, and its binding is KEPT so restore
      // re-attaches by id (the WS close on unmount only drops the viewer count). The captured-run
      // onMinimize hook also flags the persisted record minimized so a reload docks it (S2).
      expect(deleteRunMock).not.toHaveBeenCalled();
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
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it("restorePane re-seeds a docked captured pane without spawning a new run", () => {
    vi.useFakeTimers();
    try {
      deleteRunMock.mockResolvedValue(undefined);
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

  it("closeDockedPane kills a docked captured run (DELETE) and drops the dock entry", () => {
    vi.useFakeTimers();
    try {
      deleteRunMock.mockResolvedValue(undefined);
      store().addCapturedRun("claude");
      const paneId = capturedPaneIds(store().contentRefs)[0];
      if (!paneId) throw new Error("expected a captured pane");
      useCapturedRunStore.setState({ runs: { [paneId]: { provider: "claude", runId: "run-1" } } });
      store().minimizePane(paneId);
      vi.runAllTimers();
      expect(store().docked.map((docked) => docked.paneId)).toEqual([paneId]);

      store().closeDockedPane(paneId);

      // Close from the dock runs the captured-run onClose hook: the run is stopped (DELETE) and the
      // entry leaves the dock. The pane never returns to the canvas.
      expect(deleteRunMock).toHaveBeenCalledWith("run-1");
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

      expect(deleteRunMock).not.toHaveBeenCalled();
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
      deleteRunMock.mockResolvedValue(undefined);
      store().addCapturedRun("claude");
      const paneId = capturedPaneIds(store().contentRefs)[0];
      if (!paneId) throw new Error("expected a captured pane");
      useCapturedRunStore.setState({ runs: { [paneId]: { provider: "claude", runId: "run-1" } } });

      store().closePane(paneId);
      vi.runAllTimers();

      // Close is destructive: the run is stopped (DELETE) so it leaves the director too.
      expect(deleteRunMock).toHaveBeenCalledWith("run-1");
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

      expect(deleteRunMock).not.toHaveBeenCalled();
      expect(useCapturedRunStore.getState().runs["claude:k1"]).toEqual({
        provider: "claude",
        runId: "run-1",
      });
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("canvasLabStore framing", () => {
  it("frames a pane (capturing the overview) and toggles back on a second call", () => {
    resetCanvasLabStoreForTests();
    store().addPane(); // lab-1
    store().addPane(); // lab-2
    const overview = store().layout.viewport;

    store().framePane("lab-1");
    expect(framedPaneId(store().framing)).toBe("lab-1");
    expect(store().framing.overview).toEqual(overview); // pre-framing camera snapshotted
    expect(store().layout.viewport).not.toEqual(overview); // camera moved

    store().framePane("lab-1"); // toggle -> unframe
    expect(framedPaneId(store().framing)).toBeNull();
    expect(store().layout.viewport).toEqual(overview); // panned back out
  });

  it("switching frames keeps the original overview; unframe pans back out to it", () => {
    resetCanvasLabStoreForTests();
    store().addPane(); // lab-1
    store().addPane(); // lab-2
    store().addPane(); // lab-3
    const overview = store().layout.viewport;

    store().framePane("lab-2");
    const framed2 = store().layout.viewport;
    expect(framed2).not.toEqual(overview);
    expect(store().layout.focusedPaneId).toBe("lab-2");

    store().framePane("lab-3"); // switch frame without unframing first
    expect(framedPaneId(store().framing)).toBe("lab-3");
    expect(store().layout.viewport).not.toEqual(framed2); // camera moved to lab-3
    expect(store().layout.focusedPaneId).toBe("lab-3");

    store().unframe(); // single level: straight back to the original overview, no frame history
    expect(framedPaneId(store().framing)).toBeNull();
    expect(store().layout.viewport).toEqual(overview);
  });

  it("flies the camera on unframe when at or below the pane limit", () => {
    resetCanvasLabStoreForTests();
    store().addPane(); // lab-1
    store().addPane(); // lab-2
    store().framePane("lab-1");
    useCanvasLabStore.setState({ flying: false }); // simulate the frame fly having settled

    store().unframe();
    expect(store().flying).toBe(true); // unframe animated the camera
  });

  it("snaps the camera (no fly) on unframe above the pane limit", () => {
    resetCanvasLabStoreForTests();
    for (let index = 0; index <= UNFRAME_FLY_PANE_LIMIT; index += 1) store().addPane(); // limit + 1
    const overview = store().layout.viewport;
    store().framePane("lab-1");
    useCanvasLabStore.setState({ flying: false }); // simulate the frame fly having settled

    store().unframe();
    expect(store().flying).toBe(false); // unframe did not animate
    expect(store().layout.viewport).toEqual(overview); // still lands on the overview
  });

  it("does not frame when only one pane is open", () => {
    resetCanvasLabStoreForTests();
    store().addPane(); // lab-1 only
    store().framePane("lab-1");
    expect(framedPaneId(store().framing)).toBeNull();
  });

  it("organizes panes through the active strategy on add", () => {
    resetCanvasLabStoreForTests();
    store().addPane();
    store().addPane();
    const rects = Object.values(store().layout.nodes).map((node) => node.rect);
    // grid-fit places two panes side by side: same y, different x.
    expect(rects).toHaveLength(2);
    expect(rects[0]?.y).toBe(rects[1]?.y);
    expect(rects[0]?.x).not.toBe(rects[1]?.x);
  });
});

describe("canvasLabStore close", () => {
  it("reflows the survivors into the gap but never refits the camera on close", () => {
    vi.useFakeTimers();
    try {
      resetCanvasLabStoreForTests();
      // Enough panes that fit-to-content has zoomed the camera out: this is exactly the state where
      // a refit-on-close would move the camera and snap (the reported "zoom in then out").
      for (let index = 0; index < 24; index += 1) store().addPane();
      expect(store().layout.viewport.scale).toBeLessThan(1);
      const viewportBefore = store().layout.viewport;
      const target = Object.keys(store().layout.nodes)[0];
      if (!target) throw new Error("expected a seeded pane to close");

      store().closePane(target);
      vi.advanceTimersByTime(1000); // past CLOSE_DELAY_MS: the removal + reflow commit fires

      expect(store().layout.nodes[target]).toBeUndefined(); // removed, and the grid reflowed the rest
      expect(store().layout.viewport).toEqual(viewportBefore); // camera untouched: no refit on close
    } finally {
      vi.useRealTimers();
    }
  });

  it("resets manual zoom-in when closing a pane", () => {
    vi.useFakeTimers();
    try {
      resetCanvasLabStoreForTests();
      for (let index = 0; index < 24; index += 1) store().addPane();
      const fittedScale = store().layout.viewport.scale;
      expect(fittedScale).toBeLessThan(1);
      const zoomed = { panX: -240, panY: -120, scale: Math.min(1, fittedScale + 0.2) };
      store().setViewport(zoomed);

      const target = Object.keys(store().layout.nodes)[0];
      if (!target) throw new Error("expected a seeded pane to close");
      store().closePane(target);
      vi.advanceTimersByTime(200); // CLOSE_DELAY_MS: removal + reflow commit

      expect(store().layout.nodes[target]).toBeUndefined();
      expect(store().layout.viewport.scale).toBeLessThan(zoomed.scale);
      expect(store().layout.viewport).not.toEqual(zoomed);
    } finally {
      resetCanvasLabStoreForTests();
      vi.useRealTimers();
    }
  });

  it("closes a framed pane by leaving frame mode and restoring the overview", () => {
    vi.useFakeTimers();
    try {
      resetCanvasLabStoreForTests();
      store().addPane(); // lab-1
      store().addPane(); // lab-2
      const overview = store().layout.viewport;

      store().framePane("lab-1");
      expect(framedPaneId(store().framing)).toBe("lab-1");
      expect(store().layout.viewport).not.toEqual(overview);
      vi.advanceTimersByTime(1000); // frame fly settled

      store().closePane("lab-1");
      vi.advanceTimersByTime(200); // CLOSE_DELAY_MS: removal + reflow commit

      expect(store().layout.nodes["lab-1"]).toBeUndefined();
      expect(framedPaneId(store().framing)).toBeNull();
      expect(store().layout.viewport).toEqual(overview);
      expect(store().flying).toBe(true);
    } finally {
      resetCanvasLabStoreForTests();
      vi.useRealTimers();
    }
  });
});

describe("canvasLabStore expand", () => {
  it("animates pane geometry while expanding and unexpanding", () => {
    vi.useFakeTimers();
    try {
      resetCanvasLabStoreForTests();
      store().addPane(); // lab-1
      store().addPane(); // lab-2
      store().addPane(); // lab-3

      store().expandPane("lab-1");
      expect(store().expandedPaneId).toBe("lab-1");
      expect(store().flying).toBe(true);
      expect(store().paneMotion).toBe(true);
      expect("fly" in store()).toBe(false);

      vi.advanceTimersByTime(1000);
      expect(store().flying).toBe(false);
      expect(store().paneMotion).toBe(false);

      store().expandPane("lab-1"); // toggle -> unexpand
      expect(store().expandedPaneId).toBeNull();
      expect(store().flying).toBe(true);
      expect(store().paneMotion).toBe(true);
      expect("fly" in store()).toBe(false);
    } finally {
      resetCanvasLabStoreForTests();
      vi.useRealTimers();
    }
  });

  it("resetView replans expanded panes back to the active strategy", () => {
    vi.useFakeTimers();
    try {
      resetCanvasLabStoreForTests();
      store().addPane(); // lab-1
      store().addPane(); // lab-2
      store().addPane(); // lab-3
      const paneIds = ["lab-1", "lab-2", "lab-3"];
      const strategyRects = resolveLayout(store().activeStrategyId).plan(
        { paneIds, viewport: store().bounds },
        store().params,
      ).rects;

      store().expandPane("lab-1");
      expect(store().expandedPaneId).toBe("lab-1");
      expect(store().layout.nodes["lab-1"]?.rect).not.toEqual(strategyRects["lab-1"]);
      store().setViewport({ panX: -120, panY: -80, scale: 0.6 });

      store().resetView();

      expect(store().expandedPaneId).toBeNull();
      expect("fly" in store()).toBe(false);
      expect(store().layout.viewport).toEqual({ panX: 0, panY: 0, scale: 1 });
      for (const paneId of paneIds) {
        expect(store().layout.nodes[paneId]?.rect).toEqual(strategyRects[paneId]);
      }
    } finally {
      resetCanvasLabStoreForTests();
      vi.useRealTimers();
    }
  });
});

describe("canvasLabStore setParam validation", () => {
  it("clamps a number param to its control range", () => {
    resetCanvasLabStoreForTests();
    store().setParam("minW", 99999);
    expect(store().params.minW).toBe(640); // grid-fit minW max
    store().setParam("minW", 0);
    expect(store().params.minW).toBe(160); // grid-fit minW min
  });

  it("ignores an unknown key", () => {
    resetCanvasLabStoreForTests();
    store().setParam("bogus", 5);
    expect("bogus" in store().params).toBe(false);
  });

  it("ignores a value whose type does not match the control kind", () => {
    resetCanvasLabStoreForTests();
    store().setParam("minW", "320"); // number control, string value
    expect(store().params.minW).toBe(320); // unchanged default
  });

  it("accepts a valid enum value and rejects an out-of-range one", () => {
    resetCanvasLabStoreForTests();
    store().setParam("lastRow", "center");
    expect(store().params.lastRow).toBe("center");
    store().setParam("lastRow", "diagonal"); // not in options
    expect(store().params.lastRow).toBe("center"); // unchanged
  });
});

describe("canvasLabStore fit to content", () => {
  it("zooms the camera to fit the margin-padded grid frame", () => {
    resetCanvasLabStoreForTests();
    for (let index = 0; index < 12; index += 1) store().addPane();
    store().setBounds({ width: 900, height: 1000 });
    // The selector picks 3x4 (gridW 1008 x gridH ~1134). The lab fits the frame — the grid padded by
    // margin (64) on every side, 1136 x ~1262 — so that margin survives as on-screen breathing room:
    // min(1, 900/1136, 1000/1262) ≈ 0.792.
    expect(store().layout.viewport.scale).toBeCloseTo(0.792, 2);
  });

  it("resets a stale zoom-out once the content fits again (no lingering slack)", () => {
    resetCanvasLabStoreForTests();
    for (let index = 0; index < 12; index += 1) store().addPane();
    store().setBounds({ width: 900, height: 1000 }); // overflow -> scale < 1
    expect(store().layout.viewport.scale).toBeLessThan(1);
    store().setBounds({ width: 2200, height: 1400 }); // now fits -> must snap back to 1, centered
    expect(store().layout.viewport.scale).toBe(1);
    expect(store().layout.viewport.panX).toBe(0);
    expect(store().layout.viewport.panY).toBe(0);
  });
});
