import { describe, expect, it } from "vitest";
import { displayCwd } from "./formatting";

describe("displayCwd", () => {
  it("keeps the final two path segments for long absolute paths", () => {
    expect(displayCwd("/Users/alphab/Dev/LLM/DEV/helioy/attention-matters")).toBe(
      "helioy/attention-matters",
    );
  });

  it("drops a trailing slash before formatting", () => {
    expect(displayCwd("/Users/alphab/Dev/LLM/DEV/helioy/transport-matters/")).toBe(
      "helioy/transport-matters",
    );
  });

  it("preserves a single segment path", () => {
    expect(displayCwd("attention-matters")).toBe("attention-matters");
  });

  it("returns the filesystem root unchanged", () => {
    expect(displayCwd("/")).toBe("/");
  });
});
