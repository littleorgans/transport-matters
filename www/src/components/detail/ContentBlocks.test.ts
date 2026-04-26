import { describe, expect, it } from "vitest";
import type { Message, TextBlock } from "../../types";
import { blockSummary, countContentBlocks } from "./ContentBlocks";

function text(t: string): TextBlock {
  return { type: "text", text: t };
}

function msg(role: "user" | "assistant", ...blocks: TextBlock[]): Message {
  return { role, content: blocks };
}

describe("countContentBlocks", () => {
  it("returns 0 for an empty messages array", () => {
    expect(countContentBlocks([])).toBe(0);
  });

  it("returns 0 when the only message has empty content", () => {
    expect(countContentBlocks([msg("user")])).toBe(0);
  });

  it("counts blocks in a single message", () => {
    expect(countContentBlocks([msg("user", text("a"), text("b"), text("c"))])).toBe(3);
  });

  it("sums blocks across multiple messages", () => {
    const messages = [
      msg("user", text("a"), text("b"), text("c"), text("d"), text("e")),
      msg("assistant", text("reply1"), text("reply2")),
      msg("user", text("follow-up")),
    ];
    expect(countContentBlocks(messages)).toBe(8); // 5 + 2 + 1
  });

  it("skips empty messages in the total", () => {
    const messages = [msg("user"), msg("user", text("real")), msg("assistant")];
    expect(countContentBlocks(messages)).toBe(1); // 0 + 1 + 0
  });
});

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
});
