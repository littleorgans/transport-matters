import { describe, expect, it } from "vitest";
import { displayCwd, formatRelativeAge } from "./formatting";

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

describe("formatRelativeAge", () => {
  const nowMs = Date.parse("2026-04-08T12:00:00.000Z");

  it("returns invalid strings unchanged", () => {
    expect(formatRelativeAge("not-a-date", nowMs)).toBe("not-a-date");
  });

  it("formats future and sub-minute values as just now", () => {
    expect(formatRelativeAge("2026-04-08T12:00:01.000Z", nowMs)).toBe("just now");
    expect(formatRelativeAge("2026-04-08T11:59:01.000Z", nowMs)).toBe("just now");
  });

  it("switches to minutes exactly at 60 seconds", () => {
    expect(formatRelativeAge("2026-04-08T11:59:00.000Z", nowMs)).toBe("1m ago");
    expect(formatRelativeAge("2026-04-08T11:01:00.000Z", nowMs)).toBe("59m ago");
  });

  it("switches to hours exactly at 60 minutes", () => {
    expect(formatRelativeAge("2026-04-08T11:00:00.000Z", nowMs)).toBe("1h ago");
    expect(formatRelativeAge("2026-04-07T13:00:00.000Z", nowMs)).toBe("23h ago");
  });

  it("switches to days exactly at 24 hours", () => {
    expect(formatRelativeAge("2026-04-07T12:00:00.000Z", nowMs)).toBe("1d ago");
    expect(formatRelativeAge("2026-04-02T12:00:00.000Z", nowMs)).toBe("6d ago");
  });

  it("switches to UTC ISO dates exactly at seven days", () => {
    expect(formatRelativeAge("2026-04-01T12:00:00.000Z", nowMs)).toBe("2026-04-01");
  });
});
