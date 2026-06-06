import { describe, expect, it } from "vitest";
import { makeSessionEvent } from "../testUtils";
import { createSessionEventState, sessionEventReducer } from "./sessionEventReducer";

describe("sessionEventReducer", () => {
  it("appends and deduplicates by seq", () => {
    let state = createSessionEventState("session-1");
    const event = makeSessionEvent({ seq: 0 });

    state = sessionEventReducer(state, { type: "append", sessionId: "session-1", events: [event] });
    state = sessionEventReducer(state, { type: "append", sessionId: "session-1", events: [event] });

    expect(state.events).toEqual([event]);
    expect(state.highestSeq).toBe(0);
  });

  it("drops wrong session events", () => {
    const state = sessionEventReducer(createSessionEventState("session-1"), {
      type: "append",
      sessionId: "session-1",
      events: [makeSessionEvent({ session_id: "other", seq: 0 })],
    });

    expect(state.events).toEqual([]);
  });

  it("records a gap when stream skips a seq", () => {
    const state = sessionEventReducer(createSessionEventState("session-1"), {
      type: "append",
      sessionId: "session-1",
      events: [makeSessionEvent({ seq: 2 })],
    });

    expect(state.missingFromSeq).toBe(0);
  });
});
