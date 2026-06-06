import { describe, expect, it } from "vitest";
import { makeSessionSummary } from "../testUtils";
import { resolveLaunchSession } from "./launchResolution";

describe("resolveLaunchSession", () => {
  it("prefers the run id match", () => {
    const fallback = makeSessionSummary({ session_id: "fallback", run_id: "run-old" });
    const exact = makeSessionSummary({ session_id: "exact", run_id: "run-target" });

    expect(
      resolveLaunchSession([fallback, exact], {
        owner: "local",
        workspaceHash: "hash-1",
        cli: "claude",
        runId: "run-target",
      }),
    ).toEqual({ status: "resolved", session: exact });
  });

  it("falls back to the newest active session for the workspace", () => {
    const completed = makeSessionSummary({ status: "completed" });
    const active = makeSessionSummary({ session_id: "active", run_id: "run-active" });

    expect(
      resolveLaunchSession([completed, active], {
        owner: "local",
        workspaceHash: "hash-1",
        cli: "claude",
        runId: null,
      }),
    ).toEqual({ status: "resolved", session: active });
  });

  it("stays pending when lookup fields exist but no row exists", () => {
    expect(
      resolveLaunchSession([], {
        owner: "local",
        workspaceHash: "hash-1",
        cli: "claude",
        runId: "run-late",
      }),
    ).toEqual({ status: "pending" });
  });

  it("is unavailable for direct browser development without launch fields", () => {
    expect(
      resolveLaunchSession([], { owner: "local", workspaceHash: null, cli: null, runId: null }),
    ).toEqual({ status: "unavailable" });
  });
});
