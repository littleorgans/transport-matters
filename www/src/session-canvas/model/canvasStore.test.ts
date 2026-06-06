import { describe, expect, it } from "vitest";
import { makeSessionSummary } from "../testUtils";
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
});
