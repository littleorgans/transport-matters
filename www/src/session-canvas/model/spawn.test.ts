import { describe, expect, it } from "vitest";
import type { PaneContentRef } from "./paneRecords";
import { normalizeRef } from "./spawn";

describe("normalizeRef", () => {
  it("aliases a legacy session ref onto a session-timeline ref", () => {
    expect(normalizeRef({ kind: "session", owner: "local", sessionId: "s1" })).toEqual({
      kind: "session-timeline",
      owner: "local",
      sessionId: "s1",
    });
  });

  it("passes a canonical ref through unchanged", () => {
    const ref: PaneContentRef = {
      kind: "resource",
      owner: "local",
      sessionId: "s1",
      resourceId: "r1",
    };
    expect(normalizeRef(ref)).toBe(ref);
  });
});
