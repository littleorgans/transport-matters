import { describe, expect, it } from "vitest";
import { makeSessionSummary } from "../testUtils";
import { resolveLaunchSession } from "./launchResolution";

describe("resolveLaunchSession", () => {
  it("resolves the active matching harness and workspace", () => {
    const otherCli = makeSessionSummary({ sessionId: "other-harness", harness: "codex" });
    const exact = makeSessionSummary({ sessionId: "exact", harness: "claude" });

    expect(
      resolveLaunchSession([otherCli, exact], {
        owner: "local",
        workspaceHash: "hash-1",
        spaceId: null,
        worktreeId: null,
        canvasId: null,
        harness: "claude",
        runId: "run-target",
      }),
    ).toEqual({ status: "resolved", session: exact });
  });

  it("falls back to the newest active session for the workspace", () => {
    const completed = makeSessionSummary({ status: "completed" });
    const active = makeSessionSummary({ sessionId: "active" });

    expect(
      resolveLaunchSession([completed, active], {
        owner: "local",
        workspaceHash: "hash-1",
        spaceId: null,
        worktreeId: null,
        canvasId: null,
        harness: "claude",
        runId: null,
      }),
    ).toEqual({ status: "resolved", session: active });
  });

  it("stays pending when lookup fields exist but no row exists", () => {
    expect(
      resolveLaunchSession([], {
        owner: "local",
        workspaceHash: "hash-1",
        spaceId: null,
        worktreeId: null,
        canvasId: null,
        harness: "claude",
        runId: "run-late",
      }),
    ).toEqual({ status: "pending" });
  });

  it("is unavailable for direct browser development without launch fields", () => {
    expect(
      resolveLaunchSession([], {
        owner: "local",
        workspaceHash: null,
        spaceId: null,
        worktreeId: null,
        canvasId: null,
        harness: null,
        runId: null,
      }),
    ).toEqual({ status: "unavailable" });
  });
});
