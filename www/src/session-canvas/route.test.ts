import { describe, expect, it } from "vitest";
import {
  defaultCanvasId,
  isStressCanvas,
  parseCanvasLaunchContext,
  selectRootRoute,
} from "./route";

describe("session canvas route", () => {
  it("selects the canvas only for the real canvas path", () => {
    expect(selectRootRoute("/canvas")).toBe("canvas");
    expect(selectRootRoute("/")).toBe("legacy");
    expect(selectRootRoute("/legacy")).toBe("legacy");
  });

  it("parses launch context from query params", () => {
    expect(
      parseCanvasLaunchContext("?owner=local&workspace_hash=hash-1&harness=codex&run_id=run-1"),
    ).toEqual({
      owner: "local",
      workspaceHash: "hash-1",
      spaceId: null,
      worktreeId: null,
      canvasId: null,
      harness: "codex",
      runId: "run-1",
    });
    expect(parseCanvasLaunchContext("")).toEqual({
      owner: "local",
      workspaceHash: null,
      spaceId: null,
      worktreeId: null,
      canvasId: null,
      harness: null,
      runId: null,
    });
    expect(parseCanvasLaunchContext("?owner=local&workspace_hash=hash-1")).toEqual({
      owner: "local",
      workspaceHash: "hash-1",
      spaceId: null,
      worktreeId: null,
      canvasId: null,
      harness: null,
      runId: null,
    });
  });

  it("detects the stress route flag", () => {
    expect(isStressCanvas("?stress=1")).toBe(true);
    expect(isStressCanvas("?stress=0")).toBe(false);
  });
});

describe("parseCanvasLaunchContext — Space/Worktree/Canvas identity (Slice 6)", () => {
  it("reads space_id, worktree_id, and canvas_id from the query", () => {
    const launch = parseCanvasLaunchContext(
      "?workspace_hash=hash-1&space_id=space-1&worktree_id=wt-1&canvas_id=canvas-1&harness=claude",
    );
    expect(launch).toEqual({
      owner: "local",
      workspaceHash: "hash-1",
      spaceId: "space-1",
      worktreeId: "wt-1",
      canvasId: "canvas-1",
      harness: "claude",
      runId: null,
    });
  });

  it("defaults the new fields to null when absent", () => {
    const launch = parseCanvasLaunchContext("");
    expect(launch.spaceId).toBeNull();
    expect(launch.worktreeId).toBeNull();
    expect(launch.canvasId).toBeNull();
  });
});

describe("defaultCanvasId", () => {
  const base = {
    owner: "local" as const,
    workspaceHash: null,
    spaceId: null,
    worktreeId: null,
    canvasId: null,
    harness: null,
    runId: null,
  };

  it("prefers an explicit canvasId", () => {
    expect(defaultCanvasId({ ...base, canvasId: "canvas-9", spaceId: "space-1" })).toBe("canvas-9");
  });

  it("derives one default canvas per space from spaceId", () => {
    expect(defaultCanvasId({ ...base, spaceId: "space-1" })).toBe("space:space-1");
  });

  it("falls back to the legacy workspaceHash, then direct-local", () => {
    expect(defaultCanvasId({ ...base, workspaceHash: "hash-1" })).toBe("hash-1");
    expect(defaultCanvasId(base)).toBe("direct-local");
  });
});
