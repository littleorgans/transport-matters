import { describe, expect, it } from "vitest";
import type { CanvasPaneRef, PaneContentRef } from "../model/paneRecords";
import { paneIdForRef, resolveViewer, titleForRef, viewerIdForRef } from "./registry";

describe("registry pane ids", () => {
  it("generates a deterministic pane id per kind", () => {
    const cases: Array<[CanvasPaneRef, string]> = [
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
          title: "Child task",
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
      title: "Child task",
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

  it("routes each pane kind to its viewer (subagent stays a placeholder)", () => {
    const subagent: PaneContentRef = {
      kind: "subagent-timeline",
      owner: "local",
      sessionId: "s1",
      subagentId: "sub1",
      parentSessionId: "s1",
      parentSeq: 1,
      title: "Child task",
    };
    const resource: PaneContentRef = {
      kind: "resource",
      owner: "local",
      sessionId: "s1",
      resourceId: "r1",
    };
    const exchange: PaneContentRef = {
      kind: "provider-exchange",
      owner: "local",
      sessionId: "s1",
      exchangeId: "e1",
    };
    expect(viewerIdForRef(subagent)).toBe("placeholder");
    expect(viewerIdForRef(resource)).toBe("resource");
    expect(viewerIdForRef(exchange)).toBe("provider-exchange");
  });

  it("titles a subagent pane from the ref title, not a fabricated id", () => {
    const ref: PaneContentRef = {
      kind: "subagent-timeline",
      owner: "local",
      sessionId: "s1",
      subagentId: "sub1",
      parentSessionId: "s1",
      parentSeq: 3,
      title: "Investigate auth regression",
    };
    expect(titleForRef(ref)).toBe("Investigate auth regression");
  });

  it("routes the local terminal surface to the terminal viewer", () => {
    const ref: CanvasPaneRef = { kind: "terminal", owner: "local" };
    expect(viewerIdForRef(ref)).toBe("terminal");
    expect(titleForRef(ref)).toBe("Terminal");
    expect(paneIdForRef(ref)).toBe("terminal");
  });

  it("routes captured runs through the captured-run viewer, keyed by the per-pane run key", () => {
    const claude: CanvasPaneRef = {
      kind: "captured-run",
      owner: "local",
      provider: "claude",
      runKey: "claude:k1",
    };
    const codex: CanvasPaneRef = {
      kind: "captured-run",
      owner: "local",
      provider: "codex",
      runKey: "codex:k1",
    };
    expect(viewerIdForRef(claude)).toBe("captured-run");
    expect(viewerIdForRef(codex)).toBe("captured-run");
    expect(titleForRef(claude)).toBe("Claude");
    expect(titleForRef(codex)).toBe("Codex");
    // The pane id IS the per-pane run key (not the provider), so each captured pane owns its run.
    expect(paneIdForRef(claude)).toBe("claude:k1");
    expect(paneIdForRef(codex)).toBe("codex:k1");
  });

  it("gives two same-provider captured runs distinct pane ids (no provider dedupe)", () => {
    const first: CanvasPaneRef = {
      kind: "captured-run",
      owner: "local",
      provider: "claude",
      runKey: "claude:k1",
    };
    const second: CanvasPaneRef = {
      kind: "captured-run",
      owner: "local",
      provider: "claude",
      runKey: "claude:k2",
    };
    // Distinct run keys => distinct pane ids => two independent runs, never collapsed onto one.
    expect(paneIdForRef(first)).toBe("claude:k1");
    expect(paneIdForRef(second)).toBe("claude:k2");
    expect(paneIdForRef(first)).not.toBe(paneIdForRef(second));
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

  it("keeps layout geometry out of the viewer registry", () => {
    const ref: PaneContentRef = {
      kind: "resource",
      owner: "local",
      sessionId: "s1",
      resourceId: "r1",
    };
    expect(Object.hasOwn(resolveViewer(ref), "defaultRect")).toBe(false);
  });
});
