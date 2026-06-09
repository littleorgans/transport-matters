import { describe, expect, it } from "vitest";
import { parseCapturedRunFrame } from "./capturedRunFrames";

// The backend ready payload, mirroring api/v1/captured_terminal.py `_ready_frame`.
const READY = {
  type: "captured-run.ready",
  runId: "run-abc123def",
  cwd: "/work/proj",
  storageDir: "/home/.transport-matters/workspaces/proj/hash/run-abc123def",
  proxyPort: 51234,
  webPort: 7999,
  cli: "claude",
  nativeSessionId: "sess-xyz",
};

describe("parseCapturedRunFrame", () => {
  it("parses a ready frame, binding every backend field", () => {
    expect(parseCapturedRunFrame(JSON.stringify(READY))).toEqual({
      type: "captured-run.ready",
      runId: "run-abc123def",
      cwd: "/work/proj",
      storageDir: "/home/.transport-matters/workspaces/proj/hash/run-abc123def",
      proxyPort: 51234,
      webPort: 7999,
      cli: "claude",
      nativeSessionId: "sess-xyz",
    });
  });

  it("parses a ready frame without the optional nativeSessionId", () => {
    const { nativeSessionId: _omit, ...withoutSession } = READY;
    const parsed = parseCapturedRunFrame(JSON.stringify(withoutSession));
    expect(parsed).not.toBeNull();
    expect(parsed).not.toHaveProperty("nativeSessionId");
  });

  it("preserves a null proxyPort (CLI-managed proxy not bound)", () => {
    const parsed = parseCapturedRunFrame(JSON.stringify({ ...READY, proxyPort: null }));
    expect(parsed).toMatchObject({ type: "captured-run.ready", proxyPort: null });
  });

  it("parses an error frame", () => {
    const frame = { type: "captured-run.error", code: "launch_failed", message: "boom" };
    expect(parseCapturedRunFrame(JSON.stringify(frame))).toEqual(frame);
  });

  it("returns null for a ready frame missing the runId", () => {
    const { runId: _omit, ...withoutRunId } = READY;
    expect(parseCapturedRunFrame(JSON.stringify(withoutRunId))).toBeNull();
  });

  it("returns null for an unrelated control frame", () => {
    expect(
      parseCapturedRunFrame(JSON.stringify({ type: "resize", cols: 80, rows: 24 })),
    ).toBeNull();
  });

  it("returns null for non-JSON text", () => {
    expect(parseCapturedRunFrame("not json")).toBeNull();
  });

  it("returns null for a JSON primitive", () => {
    expect(parseCapturedRunFrame('"just a string"')).toBeNull();
  });
});
