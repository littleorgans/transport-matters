import { describe, expect, it } from "vitest";
import { isStressCanvas, parseCanvasLaunchContext, selectRootRoute } from "./route";

describe("session canvas route", () => {
  it("selects the canvas only for the real canvas path", () => {
    expect(selectRootRoute("/canvas")).toBe("canvas");
    expect(selectRootRoute("/")).toBe("legacy");
    expect(selectRootRoute("/legacy")).toBe("legacy");
  });

  it("parses launch context from query params", () => {
    expect(
      parseCanvasLaunchContext("?owner=local&workspace_hash=hash-1&cli=codex&run_id=run-1"),
    ).toEqual({ owner: "local", workspaceHash: "hash-1", cli: "codex", runId: "run-1" });
    expect(parseCanvasLaunchContext("")).toEqual({
      owner: "local",
      workspaceHash: null,
      cli: null,
      runId: null,
    });
  });

  it("detects the stress route flag", () => {
    expect(isStressCanvas("?stress=1")).toBe(true);
    expect(isStressCanvas("?stress=0")).toBe(false);
  });
});
