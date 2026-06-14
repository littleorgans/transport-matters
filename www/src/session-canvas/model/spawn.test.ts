import { describe, expect, it } from "vitest";
import type { PaneContentRef } from "./paneRecords";
import { createCapturedRunRef, normalizeRef } from "./spawn";

describe("createCapturedRunRef", () => {
  it("builds a captured run ref with a fresh provider-scoped run key", () => {
    const ref = createCapturedRunRef("claude", "Claude-1");

    expect(ref).toMatchObject({
      kind: "captured-run",
      owner: "local",
      provider: "claude",
      label: "Claude-1",
    });
    expect(ref.runKey.startsWith("claude:")).toBe(true);
  });

  it("omits the label when no label is provided", () => {
    const ref = createCapturedRunRef("codex");

    expect(ref).toMatchObject({
      kind: "captured-run",
      owner: "local",
      provider: "codex",
    });
    expect(ref.runKey.startsWith("codex:")).toBe(true);
    expect("label" in ref).toBe(false);
  });
});

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
