import { describe, expect, it } from "vitest";
import type { PaneContentRef } from "../model/paneRecords";
import { paneIdForRef, resolveViewer } from "./registry";

describe("registry pane ids", () => {
  it("generates a deterministic pane id per kind", () => {
    const cases: Array<[PaneContentRef, string]> = [
      [{ kind: "session-picker", owner: "local" }, "session-picker"],
      [{ kind: "session-timeline", owner: "local", sessionId: "s1" }, "transcript:s1"],
      [
        {
          kind: "subagent-timeline",
          owner: "local",
          sessionId: "s1",
          subagentId: "sub1",
          parentSessionId: "s1",
          parentSeq: 3,
        },
        "subagent:s1:sub1",
      ],
      [{ kind: "resource", owner: "local", sessionId: "s1", resourceId: "r1" }, "resource:s1:r1"],
      [
        { kind: "provider-exchange", owner: "local", sessionId: "s1", exchangeId: "e1" },
        "exchange:s1:e1",
      ],
    ];

    for (const [ref, expected] of cases) {
      expect(paneIdForRef(ref)).toBe(expected);
      // Determinism: the same ref always maps to the same id.
      expect(paneIdForRef(ref)).toBe(paneIdForRef(ref));
    }
  });

  it("dedupes subagent panes by subagent id, ignoring parent linkage", () => {
    const a: PaneContentRef = {
      kind: "subagent-timeline",
      owner: "local",
      sessionId: "s1",
      subagentId: "sub1",
      parentSessionId: "s1",
      parentSeq: 1,
    };
    const b: PaneContentRef = { ...a, parentSeq: 9 };
    expect(paneIdForRef(a)).toBe(paneIdForRef(b));
  });

  it("dedupes provider exchange panes regardless of initial view", () => {
    const a: PaneContentRef = {
      kind: "provider-exchange",
      owner: "local",
      sessionId: "s1",
      exchangeId: "e1",
    };
    const b: PaneContentRef = { ...a, initialView: "raw" };
    expect(paneIdForRef(a)).toBe(paneIdForRef(b));
  });

  it("resolves a viewer whose dedupe key is the registry pane id", () => {
    const ref: PaneContentRef = {
      kind: "resource",
      owner: "local",
      sessionId: "s1",
      resourceId: "r1",
    };
    expect(resolveViewer(ref).paneId(ref)).toBe(paneIdForRef(ref));
  });
});
