import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  framedPaneId,
  resetCanvasLabStoreForTests,
  UNFRAME_FLY_PANE_LIMIT,
  useCanvasLabStore,
} from "./canvasLabStore";
import { resetCapturedRunStoreForTests, useCapturedRunStore } from "./capturedRunStore";

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
  const terminalRef = { kind: "terminal", owner: "local" } as const;

  it("spawns a pane that carries a terminal content ref", () => {
    resetCanvasLabStoreForTests();

    store().addTerminal();

    expect(store().contentRefs["lab-1"]).toEqual(terminalRef);
    expect(store().layout.nodes["lab-1"]).toBeDefined();
  });

  it("spawns multiple independent terminals alongside demo panes", () => {
    resetCanvasLabStoreForTests();

    store().addTerminal(); // lab-1
    store().addPane(); // lab-2 (demo card/ruler, no content ref)
    store().addTerminal(); // lab-3

    expect(store().contentRefs).toEqual({ "lab-1": terminalRef, "lab-3": terminalRef });
    expect(Object.keys(store().layout.nodes).sort()).toEqual(["lab-1", "lab-2", "lab-3"]);
  });

  it("forgets a pane's content ref once its close animation completes", () => {
    vi.useFakeTimers();
    try {
      resetCanvasLabStoreForTests();
      store().addTerminal(); // lab-1
      store().addTerminal(); // lab-2

      store().closePane("lab-1");
      vi.runAllTimers();

      expect(store().contentRefs).toEqual({ "lab-2": terminalRef });
      expect(store().layout.nodes["lab-1"]).toBeUndefined();
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

  it("detaches (does NOT stop) an established run when its captured pane is closed", () => {
    vi.useFakeTimers();
    try {
      deleteRunMock.mockResolvedValue(undefined);
      store().addCapturedRun("claude");
      const paneId = capturedPaneIds(store().contentRefs)[0];
      if (!paneId) throw new Error("expected a captured pane");
      useCapturedRunStore.setState({ runs: { [paneId]: { provider: "claude", runId: "run-1" } } });

      store().closePane(paneId);
      vi.runAllTimers();

      // Closing a pane detaches: the run is NOT stopped, so it stays alive and listed for
      // the director to re-attach (the WS close on unmount drops the viewer count).
      expect(deleteRunMock).not.toHaveBeenCalled();
      // The pane and its local mapping are gone (so a reload won't auto-restore it).
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

  it("restoreCapturedPane recreates a pane at its key and is idempotent", () => {
    store().restoreCapturedPane("claude:k1", "claude");
    store().restoreCapturedPane("claude:k1", "claude"); // remount within a session: no duplicate

    expect(store().contentRefs["claude:k1"]).toEqual({
      kind: "captured-run",
      owner: "local",
      provider: "claude",
      runKey: "claude:k1",
    });
    expect(capturedPaneIds(store().contentRefs)).toEqual(["claude:k1"]);
  });

  it("attachCapturedRun opens a pane bound to an existing run id without spawning", () => {
    store().attachCapturedRun("claude", "run-existing");

    const ids = capturedPaneIds(store().contentRefs);
    expect(ids).toHaveLength(1);
    const runKey = ids[0];
    if (!runKey) throw new Error("expected a captured pane");
    // The pane owns the existing run id (adopted, not spawned).
    expect(store().contentRefs[runKey]).toEqual({
      kind: "captured-run",
      owner: "local",
      provider: "claude",
      runKey,
    });
    expect(useCapturedRunStore.getState().runs[runKey]).toEqual({
      provider: "claude",
      runId: "run-existing",
    });
    // Attach-from-list attaches to the real CLI run; it must never POST a new spawn.
    expect(createCapturedRunMock).not.toHaveBeenCalled();
  });

  it("focuses the open pane instead of duplicating it when the same run is attached twice", () => {
    store().attachCapturedRun("codex", "run-1");
    const runKey = capturedPaneIds(store().contentRefs)[0];
    if (!runKey) throw new Error("expected a captured pane");

    store().attachCapturedRun("codex", "run-1");

    expect(capturedPaneIds(store().contentRefs)).toEqual([runKey]);
    expect(store().layout.focusedPaneId).toBe(runKey);
  });
});

function capturedPaneIds(contentRefs: Record<string, { kind: string }>): string[] {
  return Object.entries(contentRefs)
    .filter(([, ref]) => ref.kind === "captured-run")
    .map(([id]) => id);
}

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

      vi.advanceTimersByTime(1000);
      expect(store().flying).toBe(false);
      expect(store().paneMotion).toBe(false);

      store().expandPane("lab-1"); // toggle -> unexpand
      expect(store().expandedPaneId).toBeNull();
      expect(store().flying).toBe(true);
      expect(store().paneMotion).toBe(true);
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
    // The selector picks 3x4 (gridW 1008 x gridH 1032). The lab fits the frame — the grid padded by
    // margin (48) on every side, 1104 x 1128 — so that margin survives as on-screen breathing room:
    // min(1, 900/1104, 1000/1128) = 900/1104 ≈ 0.815.
    expect(store().layout.viewport.scale).toBeCloseTo(0.815, 2);
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
