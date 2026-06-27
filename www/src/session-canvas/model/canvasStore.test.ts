import { beforeEach, describe, expect, it, vi } from "vitest";
import type { PaneId, WorldRect } from "../../engine";
import { resolveLayout, roundWorldRect } from "../../engine/layout";
import { FRONTEND_STORAGE_KEYS } from "../../stores/persistence";
import { makeCapturedRunRef, makeSessionSummary, rememberCapturedRun } from "../testUtils";
import { PICKER_PANE_ID } from "../viewers/registry";
import { resetCanvasStoreForTests, useCanvasStore } from "./canvasStore";
import { resetCapturedRunStoreForTests, useCapturedRunStore } from "./capturedRunStore";
import { planExpandLayout } from "./expandLayout";
import { openPaneIds } from "./layoutPlanning";

const { createCapturedRunMock, terminateRunMock } = vi.hoisted(() => ({
  createCapturedRunMock: vi.fn(),
  terminateRunMock: vi.fn(),
}));

vi.mock("../../api", () => ({
  createCapturedRun: createCapturedRunMock,
  terminateRun: terminateRunMock,
}));

// A launch context with a rooted worktree, for tests that spawn captured runs
// (addCapturedRun now requires Canvas.defaultWorktreeId, Slice 6 R3).
const ROOTED_LAUNCH = {
  owner: "local" as const,
  workspaceHash: null,
  spaceId: null,
  worktreeId: "wt-1",
  canvasId: null,
  harness: null,
  runId: null,
};

type CanvasStoreSnapshot = ReturnType<typeof useCanvasStore.getState>;

// Store rects are the strategy plan quantized at the planLayout chokepoint,
// so the expectation rounds through the same shared primitive.
function plannedRects(state: CanvasStoreSnapshot): Record<PaneId, WorldRect> {
  const paneIds = openPaneIds(state.layout);
  const planned = resolveLayout(state.activeStrategyId).plan(
    { paneIds, viewport: state.bounds },
    state.params,
  ).rects;
  return Object.fromEntries(
    Object.entries(planned).map(([paneId, rect]) => [paneId, roundWorldRect(rect)]),
  );
}

function expectRectsToMatchStrategy(state: CanvasStoreSnapshot): void {
  const expected = plannedRects(state);
  for (const [paneId, rect] of Object.entries(expected)) {
    expect(state.layout.nodes[paneId]?.rect).toEqual(rect);
  }
}

function expectNoFlyIntent(state: CanvasStoreSnapshot): void {
  expect("fly" in state).toBe(false);
}

function rectsFor(state: CanvasStoreSnapshot): Record<PaneId, WorldRect> {
  const rects: Record<PaneId, WorldRect> = {};
  for (const paneId of openPaneIds(state.layout)) {
    const rect = state.layout.nodes[paneId]?.rect;
    if (!rect) throw new Error(`expected ${paneId} to have a rect`);
    rects[paneId] = rect;
  }
  return rects;
}

describe("canvasStore", () => {
  beforeEach(() => {
    localStorage.clear();
    resetCapturedRunStoreForTests();
    createCapturedRunMock.mockReset();
    terminateRunMock.mockReset();
    terminateRunMock.mockResolvedValue(undefined);
  });

  it("starts with a stable picker pane", () => {
    resetCanvasStoreForTests();

    const state = useCanvasStore.getState();
    expect(Object.keys(state.panes)).toEqual(["session-picker"]);
    expect(state.layout.focusedPaneId).toBe("session-picker");
  });

  it("spawns or focuses one transcript pane per session", () => {
    resetCanvasStoreForTests();
    const session = makeSessionSummary({ sessionId: "session-abc" });

    useCanvasStore.getState().spawnOrFocusTranscript(session);
    useCanvasStore.getState().spawnOrFocusTranscript(session);

    const state = useCanvasStore.getState();
    expect(Object.keys(state.panes).sort()).toEqual(["session-picker", "transcript:session-abc"]);
    expect(state.layout.focusedPaneId).toBe("transcript:session-abc");
  });

  it("plans spawned panes with the active grid fit strategy", () => {
    resetCanvasStoreForTests();
    const session = makeSessionSummary({ sessionId: "session-abc" });

    useCanvasStore.getState().spawnOrFocusTranscript(session);

    const state = useCanvasStore.getState();
    expect(state.activeStrategyId).toBe("grid-fit");
    expectRectsToMatchStrategy(state);
  });

  it("replans open panes when viewport bounds change", () => {
    resetCanvasStoreForTests();
    useCanvasStore.getState().spawnOrFocusTranscript(makeSessionSummary({ sessionId: "abc" }));
    useCanvasStore
      .getState()
      .spawnPane({ kind: "resource", owner: "local", sessionId: "abc", resourceId: "r1" });
    const before = useCanvasStore.getState().layout.nodes["resource:abc:r1"]?.rect;

    useCanvasStore.getState().setBounds({ width: 640, height: 480 });

    const state = useCanvasStore.getState();
    expect(state.bounds).toEqual({ width: 640, height: 480 });
    expectRectsToMatchStrategy(state);
    expect(state.layout.nodes["resource:abc:r1"]?.rect).not.toEqual(before);
  });

  it("aliases a legacy session ref onto the session-timeline pane without duplicating", () => {
    resetCanvasStoreForTests();

    useCanvasStore.getState().spawnPane({ kind: "session", owner: "local", sessionId: "abc" });
    useCanvasStore
      .getState()
      .spawnPane({ kind: "session-timeline", owner: "local", sessionId: "abc" });

    const state = useCanvasStore.getState();
    expect(Object.keys(state.panes).sort()).toEqual(["session-picker", "transcript:abc"]);
    expect(state.panes["transcript:abc"]?.viewerId).toBe("transcript-chat");
    expect(state.panes["transcript:abc"]?.contentRef.kind).toBe("session-timeline");
    expect(state.layout.focusedPaneId).toBe("transcript:abc");
  });

  it("re-focuses the existing pane when the same resource ref is opened twice", () => {
    resetCanvasStoreForTests();
    const ref = { kind: "resource", owner: "local", sessionId: "abc", resourceId: "r1" } as const;

    useCanvasStore.getState().spawnPane(ref);
    // Move focus off the resource so the second open must re-focus it via the
    // dedupe path; otherwise the focus assertion would hold even without it.
    useCanvasStore.getState().focusPane(PICKER_PANE_ID);
    expect(useCanvasStore.getState().layout.focusedPaneId).toBe(PICKER_PANE_ID);

    useCanvasStore.getState().spawnPane(ref);

    const state = useCanvasStore.getState();
    expect(Object.keys(state.panes).sort()).toEqual(["resource:abc:r1", "session-picker"]);
    expect(state.layout.focusedPaneId).toBe("resource:abc:r1");
  });

  it("addCapturedRun inserts one pane keyed by the run key", () => {
    resetCanvasStoreForTests(ROOTED_LAUNCH);

    const paneId = useCanvasStore.getState().addCapturedRun("claude");

    const state = useCanvasStore.getState();
    const pane = state.panes[paneId];
    if (!pane) throw new Error(`expected ${paneId} to be open`);
    expect(Object.keys(state.panes).sort()).toEqual([PICKER_PANE_ID, paneId].sort());
    expect(pane.viewerId).toBe("captured-run");
    expect(pane.title).toBe("Claude");
    expect(state.layout.focusedPaneId).toBe(paneId);
    const ref = pane.contentRef;
    if (ref.kind !== "captured-run") throw new Error("expected a captured run ref");
    expect(ref.provider).toBe("claude");
    expect(ref.runKey).toBe(paneId);
    expect(ref.label).toBe("Claude");
  });

  it("addCapturedRun keeps two same-provider calls as two panes", () => {
    resetCanvasStoreForTests(ROOTED_LAUNCH);

    const firstPaneId = useCanvasStore.getState().addCapturedRun("claude");
    const secondPaneId = useCanvasStore.getState().addCapturedRun("claude");

    const state = useCanvasStore.getState();
    expect(firstPaneId).not.toBe(secondPaneId);
    expect(Object.keys(state.panes).sort()).toEqual(
      [PICKER_PANE_ID, firstPaneId, secondPaneId].sort(),
    );
    expect(state.panes[firstPaneId]?.contentRef.kind).toBe("captured-run");
    expect(state.panes[secondPaneId]?.contentRef.kind).toBe("captured-run");
    expect(state.layout.focusedPaneId).toBe(secondPaneId);
  });

  it("dockPane parks a resource in the dock without touching the layout", () => {
    resetCanvasStoreForTests();
    const ref = { kind: "resource", owner: "local", source: "path", path: "/t/x.png" } as const;
    const layoutBefore = useCanvasStore.getState().layout;

    const paneId = useCanvasStore.getState().dockPane(ref);

    const state = useCanvasStore.getState();
    // the no-double-resize contract: the layout object is untouched
    expect(state.layout).toBe(layoutBefore);
    expect(state.panes[paneId]).toBeUndefined();
    expect(state.docked[0]?.paneId).toBe(paneId);
    expect(state.docked[0]?.ref).toEqual(ref);
    expect(state.docked[0]?.record?.contentRef).toEqual(ref);
  });

  it("dockPane keeps a single entry per ref, bumped to the front", () => {
    resetCanvasStoreForTests();
    const refA = { kind: "resource", owner: "local", source: "path", path: "/t/a.png" } as const;
    const refB = { kind: "resource", owner: "local", source: "path", path: "/t/b.png" } as const;

    useCanvasStore.getState().dockPane(refA);
    useCanvasStore.getState().dockPane(refB);
    const paneId = useCanvasStore.getState().dockPane(refA);

    const docked = useCanvasStore.getState().docked;
    expect(docked).toHaveLength(2);
    expect(docked[0]?.paneId).toBe(paneId);
  });

  it("dockPane of an open pane minimizes it through the dismiss flow", () => {
    resetCanvasStoreForTests();
    const ref = { kind: "resource", owner: "local", source: "path", path: "/t/x.png" } as const;
    const paneId = useCanvasStore.getState().spawnPane(ref);

    useCanvasStore.getState().dockPane(ref);

    expect(useCanvasStore.getState().layout.nodes[paneId]?.lifecycle).toBe("closing");
  });

  it("a never-opened docked resource restores into a planned pane", () => {
    resetCanvasStoreForTests();
    const ref = { kind: "resource", owner: "local", source: "path", path: "/t/x.png" } as const;
    const paneId = useCanvasStore.getState().dockPane(ref);

    useCanvasStore.getState().restorePane(paneId);

    const state = useCanvasStore.getState();
    expect(state.panes[paneId]?.contentRef).toEqual(ref);
    expect(state.layout.nodes[paneId]?.lifecycle).toBe("open");
    expect(state.docked).toHaveLength(0);
  });

  it("closePane stops an established captured run through the core lifecycle policy", () => {
    vi.useFakeTimers();
    try {
      resetCanvasStoreForTests();
      rememberCapturedRun();
      useCanvasStore.getState().spawnPane(makeCapturedRunRef());

      useCanvasStore.getState().closePane("claude:k1");
      vi.runAllTimers();

      expect(terminateRunMock).toHaveBeenCalledWith("run-1");
      expect(terminateRunMock).toHaveBeenCalledTimes(1);
      expect(useCapturedRunStore.getState().runs["claude:k1"]).toBeUndefined();
      expect(useCanvasStore.getState().panes["claude:k1"]).toBeUndefined();
    } finally {
      vi.useRealTimers();
    }
  });

  it("addCapturedRun then closePane stops the run through the real spawn path", () => {
    vi.useFakeTimers();
    try {
      resetCanvasStoreForTests(ROOTED_LAUNCH);
      const paneId = useCanvasStore.getState().addCapturedRun("claude");
      rememberCapturedRun(paneId);

      useCanvasStore.getState().closePane(paneId);
      vi.runAllTimers();

      expect(terminateRunMock).toHaveBeenCalledWith("run-1");
      expect(terminateRunMock).toHaveBeenCalledTimes(1);
      expect(useCapturedRunStore.getState().runs[paneId]).toBeUndefined();
      expect(useCanvasStore.getState().panes[paneId]).toBeUndefined();
    } finally {
      vi.useRealTimers();
    }
  });

  it("closeDockedPane stops a docked captured run through the core lifecycle policy", () => {
    resetCanvasStoreForTests();
    rememberCapturedRun();
    const paneId = useCanvasStore.getState().dockPane(makeCapturedRunRef());

    useCanvasStore.getState().closeDockedPane(paneId);

    expect(terminateRunMock).toHaveBeenCalledWith("run-1");
    expect(terminateRunMock).toHaveBeenCalledTimes(1);
    expect(useCapturedRunStore.getState().runs["claude:k1"]).toBeUndefined();
    expect(useCanvasStore.getState().docked).toEqual([]);
  });

  it("closeDockedPane stops a persisted captured run after reload without spawning or mounting the viewer", async () => {
    resetCanvasStoreForTests();
    const runKey = "claude:rehydrated";
    localStorage.setItem(
      FRONTEND_STORAGE_KEYS.capturedRunStore,
      JSON.stringify({
        version: 3,
        state: { runs: { [runKey]: { provider: "claude", runId: "run-rehydrated" } } },
      }),
    );
    await useCapturedRunStore.persist.rehydrate();
    const paneId = useCanvasStore.getState().dockPane(makeCapturedRunRef(runKey));

    useCanvasStore.getState().closeDockedPane(paneId);

    expect(createCapturedRunMock).not.toHaveBeenCalled();
    expect(terminateRunMock).toHaveBeenCalledWith("run-rehydrated");
    expect(useCapturedRunStore.getState().runs[runKey]).toBeUndefined();
    expect(useCanvasStore.getState().docked).toEqual([]);
  });

  it("dropCapturedRunPane removes open and docked captured refs without forgetting runs", () => {
    resetCanvasStoreForTests();
    rememberCapturedRun("claude:open", "run-open");
    rememberCapturedRun("claude:docked", "run-docked");
    useCanvasStore.getState().spawnPane(makeCapturedRunRef("claude:open"));
    useCanvasStore.getState().dockPane(makeCapturedRunRef("claude:docked"));

    useCanvasStore.getState().dropCapturedRunPane("claude:open");
    useCanvasStore.getState().dropCapturedRunPane("claude:docked");

    const state = useCanvasStore.getState();
    const capturedRuns = useCapturedRunStore.getState().runs;
    expect(capturedRuns["claude:open"]?.runId).toBe("run-open");
    expect(capturedRuns["claude:docked"]?.runId).toBe("run-docked");
    expect(state.panes["claude:open"]).toBeUndefined();
    expect(state.layout.nodes["claude:open"]).toBeUndefined();
    expect(state.layout.order).not.toContain("claude:open");
    expect(state.docked).toEqual([]);
  });

  it("restorePaneAtIndex restores the docked pane into the order slot the drop chose", () => {
    resetCanvasStoreForTests();
    const refA = { kind: "resource", owner: "local", source: "path", path: "/t/a.png" } as const;
    const refB = { kind: "resource", owner: "local", source: "path", path: "/t/b.png" } as const;
    const refC = { kind: "resource", owner: "local", source: "path", path: "/t/c.png" } as const;
    useCanvasStore.getState().spawnPane(refA);
    useCanvasStore.getState().spawnPane(refB);
    const orderBefore = useCanvasStore.getState().layout.order;
    const paneId = useCanvasStore.getState().dockPane(refC);

    useCanvasStore.getState().restorePaneAtIndex(paneId, 1);

    const state = useCanvasStore.getState();
    expect(state.docked).toEqual([]);
    expect(state.layout.nodes[paneId]?.lifecycle).toBe("open");
    // spliced into the chosen slot, not appended: the one path where the user names the position
    expect(state.layout.order).toEqual([orderBefore[0], paneId, ...orderBefore.slice(1)]);
    expectRectsToMatchStrategy(state);
  });

  it("restorePaneAtIndex clamps an out-of-range index to the tail", () => {
    resetCanvasStoreForTests();
    const refA = { kind: "resource", owner: "local", source: "path", path: "/t/a.png" } as const;
    const refC = { kind: "resource", owner: "local", source: "path", path: "/t/c.png" } as const;
    useCanvasStore.getState().spawnPane(refA);
    const paneId = useCanvasStore.getState().dockPane(refC);

    useCanvasStore.getState().restorePaneAtIndex(paneId, 99);

    const order = useCanvasStore.getState().layout.order;
    expect(order[order.length - 1]).toBe(paneId);
    expect(useCanvasStore.getState().docked).toEqual([]);
  });

  it("minimizes a pane into the dock and restores it with a planned rect", () => {
    vi.useFakeTimers();
    try {
      resetCanvasStoreForTests();
      useCanvasStore
        .getState()
        .spawnOrFocusTranscript(
          makeSessionSummary({ sessionId: "session-abc", title: "Agent transcript" }),
        );
      useCanvasStore.getState().spawnPane({
        kind: "resource",
        owner: "local",
        sessionId: "session-abc",
        resourceId: "r1",
      });

      useCanvasStore.getState().minimizePane("transcript:session-abc");
      vi.runAllTimers();

      expect(useCanvasStore.getState().panes["transcript:session-abc"]).toBeUndefined();
      expect(useCanvasStore.getState().layout.nodes["transcript:session-abc"]).toBeUndefined();
      expect(useCanvasStore.getState().docked[0]?.record?.title).toBe("Agent transcript");
      expectNoFlyIntent(useCanvasStore.getState());

      useCanvasStore.getState().restorePane("transcript:session-abc");

      const restored = useCanvasStore.getState();
      expect(restored.docked).toEqual([]);
      expect(restored.panes["transcript:session-abc"]?.title).toBe("Agent transcript");
      expect(restored.layout.nodes["transcript:session-abc"]).toBeDefined();
      expectRectsToMatchStrategy(restored);
    } finally {
      vi.useRealTimers();
    }
  });

  it("expands through the shared hero plus grid overflow planner and unexpands to the strategy", () => {
    resetCanvasStoreForTests();
    useCanvasStore.getState().spawnOrFocusTranscript(makeSessionSummary({ sessionId: "abc" }));
    useCanvasStore
      .getState()
      .spawnPane({ kind: "resource", owner: "local", sessionId: "abc", resourceId: "r1" });

    useCanvasStore.getState().expandPane("transcript:abc");

    const expanded = useCanvasStore.getState();
    expectNoFlyIntent(expanded);
    const paneIds = openPaneIds(expanded.layout);
    const expected = planExpandLayout({
      paneIds,
      expandedPaneId: "transcript:abc",
      viewport: expanded.bounds,
    });
    expect(expanded.expandedPaneId).toBe("transcript:abc");
    for (const [paneId, rect] of Object.entries(expected.rects)) {
      expect(expanded.layout.nodes[paneId]?.rect).toEqual(roundWorldRect(rect));
    }
    expect(expanded.layout.viewport).toEqual(expected.camera);

    useCanvasStore.getState().unexpand();

    const unexpanded = useCanvasStore.getState();
    expectNoFlyIntent(unexpanded);
    expect(unexpanded.expandedPaneId).toBeNull();
    expectRectsToMatchStrategy(unexpanded);
  });

  it("guards expand for single, missing, and docked panes", () => {
    vi.useFakeTimers();
    try {
      resetCanvasStoreForTests();
      useCanvasStore.getState().expandPane(PICKER_PANE_ID);
      expect(useCanvasStore.getState().expandedPaneId).toBeNull();

      useCanvasStore.getState().spawnOrFocusTranscript(makeSessionSummary({ sessionId: "abc" }));
      useCanvasStore.getState().minimizePane("transcript:abc");
      vi.runAllTimers();

      useCanvasStore.getState().expandPane("transcript:abc");
      expect(useCanvasStore.getState().expandedPaneId).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("frames by moving the camera only and unframes back to the overview", () => {
    resetCanvasStoreForTests();
    useCanvasStore.getState().spawnOrFocusTranscript(makeSessionSummary({ sessionId: "abc" }));
    useCanvasStore
      .getState()
      .spawnPane({ kind: "resource", owner: "local", sessionId: "abc", resourceId: "r1" });
    const overview = useCanvasStore.getState().layout.viewport;
    const rectsBefore = rectsFor(useCanvasStore.getState());

    useCanvasStore.getState().framePane("transcript:abc");

    const framed = useCanvasStore.getState();
    expectNoFlyIntent(framed);
    expect(framed.framing.paneId).toBe("transcript:abc");
    expect(framed.layout.viewport).not.toEqual(overview);
    expect(rectsFor(framed)).toEqual(rectsBefore);

    useCanvasStore.getState().unframe();

    expect(useCanvasStore.getState().framing.paneId).toBeNull();
    expectNoFlyIntent(useCanvasStore.getState());
    expect(useCanvasStore.getState().layout.viewport).toEqual(overview);
    expect(rectsFor(useCanvasStore.getState())).toEqual(rectsBefore);
  });

  describe("canvas identity (Slice 6)", () => {
    it("mints a default canvasId per space and promotes defaultWorktreeId", () => {
      resetCanvasStoreForTests();
      useCanvasStore.getState().initializeCanvas({
        owner: "local",
        workspaceHash: "hash-1",
        spaceId: "space-1",
        worktreeId: "wt-1",
        canvasId: null,
        harness: null,
        runId: null,
      });

      const state = useCanvasStore.getState();
      expect(state.canvasId).toBe("space:space-1");
      expect(state.spaceId).toBe("space-1");
      expect(state.defaultWorktreeId).toBe("wt-1");
      expect(state.workspaceHash).toBe("hash-1");
    });

    it("falls back to direct-local with no space and no worktree root", () => {
      resetCanvasStoreForTests();
      const state = useCanvasStore.getState();
      expect(state.canvasId).toBe("direct-local");
      expect(state.spaceId).toBeNull();
      expect(state.defaultWorktreeId).toBeNull();
    });

    it("switching to a new canvas starts isolated, not a clone of the previous canvas", () => {
      localStorage.clear();
      resetCanvasStoreForTests();
      // Arrange canvas A with a captured-run pane on top of the picker.
      useCanvasStore.getState().initializeCanvas({
        owner: "local",
        workspaceHash: null,
        spaceId: "space-a",
        worktreeId: "wt-a",
        canvasId: null,
        harness: null,
        runId: null,
      });
      useCanvasStore.getState().addCapturedRun("claude");
      expect(
        Object.values(useCanvasStore.getState().panes).some(
          (pane) => pane.contentRef.kind === "captured-run",
        ),
      ).toBe(true);

      // Switch to a brand-new canvas B with no cached blob.
      useCanvasStore.getState().initializeCanvas({
        owner: "local",
        workspaceHash: null,
        spaceId: "space-b",
        worktreeId: "wt-b",
        canvasId: null,
        harness: null,
        runId: null,
      });

      const stateB = useCanvasStore.getState();
      expect(stateB.canvasId).toBe("space:space-b");
      expect(stateB.defaultWorktreeId).toBe("wt-b");
      // Isolated: B does NOT inherit canvas A's captured-run pane (no clone leak).
      expect(
        Object.values(stateB.panes).some((pane) => pane.contentRef.kind === "captured-run"),
      ).toBe(false);
    });
  });

  describe("addCapturedRun roots on defaultWorktreeId (Slice 6)", () => {
    it("stamps the canvas defaultWorktreeId onto the captured-run ref", () => {
      resetCanvasStoreForTests();
      useCanvasStore.getState().initializeCanvas({
        owner: "local",
        workspaceHash: null,
        spaceId: "space-1",
        worktreeId: "wt-7",
        canvasId: null,
        harness: null,
        runId: null,
      });

      const paneId = useCanvasStore.getState().addCapturedRun("claude");
      const ref = useCanvasStore.getState().panes[paneId]?.contentRef;
      expect(ref).toMatchObject({ kind: "captured-run", provider: "claude", worktreeId: "wt-7" });
    });

    it("throws when no worktree root is available", () => {
      resetCanvasStoreForTests();
      expect(() => useCanvasStore.getState().addCapturedRun("claude")).toThrow(/worktree/i);
    });

    it("a per-spawn worktreeId targets two worktrees as coexisting panes, leaving the default untouched", () => {
      resetCanvasStoreForTests();
      useCanvasStore.getState().initializeCanvas({
        owner: "local",
        workspaceHash: null,
        spaceId: "space-1",
        worktreeId: "wt-default",
        canvasId: null,
        harness: null,
        runId: null,
      });

      const paneA = useCanvasStore.getState().addCapturedRun("claude", undefined, "wt-a");
      const paneB = useCanvasStore.getState().addCapturedRun("codex", undefined, "wt-b");

      const refA = useCanvasStore.getState().panes[paneA]?.contentRef;
      const refB = useCanvasStore.getState().panes[paneB]?.contentRef;
      expect(refA).toMatchObject({ kind: "captured-run", provider: "claude", worktreeId: "wt-a" });
      expect(refB).toMatchObject({ kind: "captured-run", provider: "codex", worktreeId: "wt-b" });
      // Two distinct, coexisting panes, no toggling of a single global default.
      expect(paneA).not.toBe(paneB);
      expect(useCanvasStore.getState().defaultWorktreeId).toBe("wt-default");
    });

    it("falls back to the canvas default worktree when no per-spawn target is given", () => {
      resetCanvasStoreForTests();
      useCanvasStore.getState().initializeCanvas({
        owner: "local",
        workspaceHash: null,
        spaceId: "space-1",
        worktreeId: "wt-default",
        canvasId: null,
        harness: null,
        runId: null,
      });

      const paneId = useCanvasStore.getState().addCapturedRun("claude");
      const ref = useCanvasStore.getState().panes[paneId]?.contentRef;
      expect(ref).toMatchObject({ kind: "captured-run", worktreeId: "wt-default" });
    });
  });

  describe("adoptDefaultWorktree (meta seeding)", () => {
    const WORKTREELESS_LAUNCH = {
      owner: "local" as const,
      workspaceHash: null,
      spaceId: null,
      worktreeId: null,
      canvasId: null,
      harness: null,
      runId: null,
    };

    it("seeds the default spawn target when the launch URL carried none", () => {
      resetCanvasStoreForTests();
      // Mirrors the desktop mount order: initializeCanvas (worktree-less URL) then adopt.
      useCanvasStore.getState().initializeCanvas(WORKTREELESS_LAUNCH);
      expect(useCanvasStore.getState().defaultWorktreeId).toBeNull();

      useCanvasStore.getState().adoptDefaultWorktree("space-meta", "wt-meta");

      const state = useCanvasStore.getState();
      expect(state.defaultWorktreeId).toBe("wt-meta");
      expect(state.spaceId).toBe("space-meta");
      // The spawn that previously threw now roots on the adopted worktree.
      const paneId = state.addCapturedRun("claude");
      expect(useCanvasStore.getState().panes[paneId]?.contentRef).toMatchObject({
        kind: "captured-run",
        worktreeId: "wt-meta",
      });
    });

    it("never overrides an explicit URL worktree", () => {
      resetCanvasStoreForTests();
      useCanvasStore.getState().initializeCanvas({
        owner: "local",
        workspaceHash: null,
        spaceId: "space-url",
        worktreeId: "wt-url",
        canvasId: null,
        harness: null,
        runId: null,
      });

      useCanvasStore.getState().adoptDefaultWorktree("space-meta", "wt-meta");

      const state = useCanvasStore.getState();
      expect(state.defaultWorktreeId).toBe("wt-url");
      expect(state.spaceId).toBe("space-url");
    });

    it("a worktree-less re-init of the same canvas keeps the adopted default", () => {
      resetCanvasStoreForTests();
      useCanvasStore.getState().adoptDefaultWorktree("space-meta", "wt-meta");

      // The desktop default launch re-runs initializeCanvas with a worktree-less URL;
      // a re-init must not strip the adopted default back to null.
      useCanvasStore.getState().initializeCanvas(WORKTREELESS_LAUNCH);

      expect(useCanvasStore.getState().defaultWorktreeId).toBe("wt-meta");
    });
  });
});
