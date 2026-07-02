import { describe, expect, it } from "vitest";
import { blockKey, blockSummary } from "./contentBlocks";
import type { ContentBlock, ToolResultBlock } from "./types/ir";

function toolResult(overrides: Partial<ToolResultBlock> = {}): ToolResultBlock {
  return {
    type: "tool_result",
    tool_use_id: "toolu_01MiLL7GyXKvFTneZmojAazu",
    content: [],
    is_error: false,
    ...overrides,
  };
}

describe("blockSummary", () => {
  it.each([
    ["Claude Agent", "toolu_01MiLL7GyXKvFTneZmojAazu"],
    ["Codex spawn_agent", "call_Lnc2jHDm8pTHtzdhTGeMOgdH"],
  ])("shows the full %s tool use id", (name, id) => {
    const block = {
      type: "tool_use",
      id,
      name,
      input: {},
    } as const;

    expect(blockSummary(block)).toBe(`${name}  ·  ${id}`);
  });

  it("passes short text through trimmed", () => {
    expect(blockSummary({ type: "text", text: "  hello  " })).toBe("hello");
  });

  it("marks whitespace-only text as empty", () => {
    expect(blockSummary({ type: "text", text: "   \n " })).toBe("(empty)");
  });

  it("truncates long text at maxPreview with an ellipsis", () => {
    const long = "x".repeat(300);
    expect(blockSummary({ type: "text", text: long }, 10)).toBe(`${"x".repeat(10)}…`);
  });

  it("points a tool result at the first 8 chars of its tool use id", () => {
    expect(blockSummary(toolResult())).toBe("→ toolu_01");
  });

  it("flags an errored tool result", () => {
    expect(blockSummary(toolResult({ is_error: true }))).toBe("→ toolu_01  [error]");
  });

  it("summarizes thinking by reasoning length", () => {
    expect(blockSummary({ type: "thinking", text: "y".repeat(1234) })).toBe(
      "1,234 chars of reasoning",
    );
  });

  it("labels image and unknown blocks", () => {
    expect(blockSummary({ type: "image", source: {} })).toBe("image");
    expect(blockSummary({ type: "unknown", raw: {} })).toBe("unknown block");
  });
});

describe("blockKey", () => {
  it("keys tool use blocks by tool use id", () => {
    const block: ContentBlock = { type: "tool_use", id: "tu-abc", name: "Read", input: {} };
    expect(blockKey(block, 3)).toBe("tu-tu-abc");
  });

  it("keys tool result blocks by their tool use id", () => {
    expect(blockKey(toolResult({ tool_use_id: "call_1" }), 0)).toBe("tr-call_1");
  });

  it.each([
    [{ type: "text", text: "a" } as const, 0, "text-0"],
    [{ type: "thinking", text: "a" } as const, 4, "thinking-4"],
    [{ type: "image", source: {} } as const, 2, "image-2"],
    [{ type: "unknown", raw: {} } as const, 7, "unknown-7"],
  ])("keys %o by type and index", (block, idx, expected) => {
    expect(blockKey(block, idx)).toBe(expected);
  });
});
