import { describe, expect, it } from "vitest";
import { paneIdForRef, titleForRef } from "../viewers/registry";
import { isCanvasPaneRef, isPaneContentRef } from "./paneRecords";

describe("locator resource refs", () => {
  const pathRef = {
    kind: "resource",
    owner: "local",
    source: "path",
    path: "/tmp/shot.png",
  } as const;
  const urlRef = {
    kind: "resource",
    owner: "local",
    source: "url",
    url: "https://x.test/a/cat.png",
  } as const;

  it("guards accept path and url sources", () => {
    expect(isPaneContentRef(pathRef)).toBe(true);
    expect(isPaneContentRef(urlRef)).toBe(true);
    expect(isCanvasPaneRef(pathRef)).toBe(true);
  });

  it("guards reject malformed locator refs", () => {
    expect(isPaneContentRef({ kind: "resource", owner: "local", source: "path" })).toBe(false);
    expect(isPaneContentRef({ kind: "resource", owner: "local", source: "url", url: 7 })).toBe(
      false,
    );
  });

  it("db refs still validate", () => {
    expect(
      isPaneContentRef({
        kind: "resource",
        owner: "local",
        sessionId: "s",
        resourceId: "r",
      }),
    ).toBe(true);
  });

  it("locator refs survive the persistence JSON round trip and guard", () => {
    expect(isCanvasPaneRef(JSON.parse(JSON.stringify(pathRef)))).toBe(true);
    expect(isCanvasPaneRef(JSON.parse(JSON.stringify(urlRef)))).toBe(true);
  });

  it("pane identity is the locator string", () => {
    expect(paneIdForRef(pathRef)).toBe("resource:path:/tmp/shot.png");
    expect(paneIdForRef(urlRef)).toBe("resource:url:https://x.test/a/cat.png");
  });

  it("titles are the basename or url tail", () => {
    expect(titleForRef(pathRef)).toBe("shot.png");
    expect(titleForRef(urlRef)).toBe("cat.png");
  });
});

describe("isPaneContentRef — worktree-rooting (R3)", () => {
  it("requires worktreeId on a terminal ref", () => {
    expect(isPaneContentRef({ kind: "terminal", owner: "local", worktreeId: "wt-1" })).toBe(true);
    expect(isPaneContentRef({ kind: "terminal", owner: "local", label: "T" })).toBe(false);
  });

  it("requires worktreeId on a captured-run ref", () => {
    expect(
      isPaneContentRef({
        kind: "captured-run",
        owner: "local",
        provider: "claude",
        runKey: "claude:1",
        worktreeId: "wt-1",
      }),
    ).toBe(true);
    expect(
      isPaneContentRef({
        kind: "captured-run",
        owner: "local",
        provider: "claude",
        runKey: "claude:1",
      }),
    ).toBe(false);
  });

  it("treats worktreeId as optional on a resource(url) ref", () => {
    expect(
      isPaneContentRef({ kind: "resource", owner: "local", source: "url", url: "https://x" }),
    ).toBe(true);
    expect(
      isPaneContentRef({
        kind: "resource",
        owner: "local",
        source: "url",
        url: "https://x",
        worktreeId: "wt-1",
      }),
    ).toBe(true);
    expect(
      isPaneContentRef({
        kind: "resource",
        owner: "local",
        source: "url",
        url: "https://x",
        worktreeId: 7,
      }),
    ).toBe(false);
  });

  it("round-trips a captured-run ref with and without sessionId (Slice 6 resume anchor)", () => {
    const base = {
      kind: "captured-run" as const,
      owner: "local" as const,
      provider: "claude" as const,
      runKey: "claude:1",
      worktreeId: "wt-1",
    };
    // Legacy pane: no sessionId. Round-trips clean and stays undefined.
    const legacy = JSON.parse(JSON.stringify(base));
    expect(isPaneContentRef(legacy)).toBe(true);
    expect(legacy.sessionId).toBeUndefined();
    // Bound pane: sessionId persists through serialize and passes the guard.
    const bound = JSON.parse(JSON.stringify({ ...base, sessionId: "sess-7" }));
    expect(isPaneContentRef(bound)).toBe(true);
    expect(bound.sessionId).toBe("sess-7");
    // A non-string sessionId is rejected.
    expect(isPaneContentRef({ ...base, sessionId: 7 })).toBe(false);
  });
});
