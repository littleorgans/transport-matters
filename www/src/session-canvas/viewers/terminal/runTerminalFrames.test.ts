import { describe, expect, it } from "vitest";
import { parseRunErrorFrame } from "./runTerminalFrames";

describe("parseRunErrorFrame", () => {
  it("parses a run.error control frame into a typed error", () => {
    const parsed = parseRunErrorFrame(
      JSON.stringify({ type: "run.error", code: "run_not_found", message: "run not found: x" }),
    );
    expect(parsed).toEqual({
      type: "run.error",
      code: "run_not_found",
      message: "run not found: x",
    });
  });

  it("defaults a missing message to an empty string", () => {
    const parsed = parseRunErrorFrame(JSON.stringify({ type: "run.error", code: "launch_failed" }));
    expect(parsed).toEqual({ type: "run.error", code: "launch_failed", message: "" });
  });

  it("ignores the ready and scrollback-end frames (not errors)", () => {
    expect(parseRunErrorFrame(JSON.stringify({ type: "run.terminal.ready", run: {} }))).toBeNull();
    expect(parseRunErrorFrame(JSON.stringify({ type: "run.terminal.scrollback-end" }))).toBeNull();
  });

  it("returns null for non-JSON and non-object frames", () => {
    expect(parseRunErrorFrame("not json")).toBeNull();
    expect(parseRunErrorFrame("42")).toBeNull();
    expect(parseRunErrorFrame(JSON.stringify({ type: "run.error" }))).toBeNull();
  });
});
