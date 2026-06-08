import { describe, expect, it } from "vitest";
import { makeSessionSummary } from "../testUtils";
import { PICKER_PANE_ID } from "../viewers/registry";
import { resetCanvasStoreForTests, useCanvasStore } from "./canvasStore";

describe("canvasStore", () => {
  it("starts with a stable picker pane", () => {
    resetCanvasStoreForTests();

    const state = useCanvasStore.getState();
    expect(Object.keys(state.panes)).toEqual(["session-picker"]);
    expect(state.layout.focusedPaneId).toBe("session-picker");
  });

  it("spawns or focuses one transcript pane per session", () => {
    resetCanvasStoreForTests();
    const session = makeSessionSummary({ session_id: "session-abc" });

    useCanvasStore.getState().spawnOrFocusTranscript(session);
    useCanvasStore.getState().spawnOrFocusTranscript(session);

    const state = useCanvasStore.getState();
    expect(Object.keys(state.panes).sort()).toEqual(["session-picker", "transcript:session-abc"]);
    expect(state.layout.focusedPaneId).toBe("transcript:session-abc");
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
});
