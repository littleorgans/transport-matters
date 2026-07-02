import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Message, Override } from "../../types";
import { GlobalSection } from "./GlobalSection";

function thinkingMessage(count: number): Message {
  const content: Message["content"] = [];
  for (let i = 0; i < count; i++) {
    content.push({ type: "thinking", text: `t${i}` });
  }
  return { role: "assistant", content };
}

function toolMessages(count: number): Message[] {
  // Each tool call is a pair: assistant emits tool_use, user replies
  // with tool_result. Splitting into two messages mirrors the shape
  // the Anthropic wire format uses in real payloads.
  const assistant: Message = { role: "assistant", content: [] };
  const user: Message = { role: "user", content: [] };
  for (let i = 0; i < count; i++) {
    assistant.content.push({
      type: "tool_use",
      id: `tu-${i}`,
      name: "bash",
      input: {},
    });
    user.content.push({
      type: "tool_result",
      tool_use_id: `tu-${i}`,
      content: [],
      is_error: false,
    });
  }
  return [assistant, user];
}

describe("GlobalSection", () => {
  it("UNCHECKED state: both toggles render 'Strip all X' with aria-checked=false", () => {
    render(
      <GlobalSection
        messages={[thinkingMessage(3), ...toolMessages(2)]}
        overrides={[]}
        onOverride={vi.fn()}
      />,
    );

    // The aria-label is the stable idle phrasing in either state, so
    // the test query is the same regardless of checked state.
    const thinking = screen.getByRole("switch", { name: "Strip all thinking blocks" });
    const tools = screen.getByRole("switch", { name: "Strip all tool calls" });

    expect(thinking.getAttribute("aria-checked")).toBe("false");
    expect(tools.getAttribute("aria-checked")).toBe("false");
    expect(screen.getByText("Strip all thinking blocks")).toBeTruthy();
    expect(screen.getByText("Strip all tool calls")).toBeTruthy();
  });

  it("CHECKED state: thinking label swaps to 'Strip {count}' when every block is toggled off", () => {
    const message = thinkingMessage(3);
    const overrides: Override[] = message.content.map((_, blkIdx) => ({
      kind: "message_block_toggle",
      target: `msg:0:blk:${blkIdx}`,
      value: false,
    }));
    render(<GlobalSection messages={[message]} overrides={overrides} onOverride={vi.fn()} />);

    expect(screen.getByText("Strip 3 thinking blocks")).toBeTruthy();
    expect(
      screen
        .getByRole("switch", { name: "Strip all thinking blocks" })
        .getAttribute("aria-checked"),
    ).toBe("true");
    // Other half is unrelated and stays idle.
    expect(screen.getByText("Strip all tool calls")).toBeTruthy();
  });

  it("tool-call count uses tool_use blocks only, not use+result totals", () => {
    // 2 calls spans 2 tool_use + 2 tool_result = 4 blocks, but the
    // label must say "Strip 2 tool calls" so the number matches the
    // user's mental model of one call = one request/response pair.
    const messages = toolMessages(2);
    const overrides: Override[] = [];
    messages.forEach((msg, m) => {
      msg.content.forEach((_, b) => {
        overrides.push({
          kind: "message_block_toggle",
          target: `msg:${m}:blk:${b}`,
          value: false,
        });
      });
    });
    render(<GlobalSection messages={messages} overrides={overrides} onOverride={vi.fn()} />);

    expect(screen.getByText("Strip 2 tool calls")).toBeTruthy();
    expect(
      screen.getByRole("switch", { name: "Strip all tool calls" }).getAttribute("aria-checked"),
    ).toBe("true");
  });

  it("PARTIAL state: unchecked when only some targets are toggled off", () => {
    const messages = [thinkingMessage(3)];
    const overrides: Override[] = [
      // Only one of three thinking blocks has a toggle override.
      { kind: "message_block_toggle", target: "msg:0:blk:0", value: false },
    ];
    render(<GlobalSection messages={messages} overrides={overrides} onOverride={vi.fn()} />);

    expect(
      screen
        .getByRole("switch", { name: "Strip all thinking blocks" })
        .getAttribute("aria-checked"),
    ).toBe("false");
    // Stays on the idle label while not fully stripped.
    expect(screen.getByText("Strip all thinking blocks")).toBeTruthy();
  });

  it("clicking unchecked thinking toggle emits value=false for every thinking block", () => {
    const onOverride = vi.fn();
    const messages = [thinkingMessage(2)];
    render(<GlobalSection messages={messages} overrides={[]} onOverride={onOverride} />);

    fireEvent.click(screen.getByRole("switch", { name: "Strip all thinking blocks" }));

    expect(onOverride).toHaveBeenCalledWith([
      { kind: "message_block_toggle", target: "msg:0:blk:0", value: false },
      { kind: "message_block_toggle", target: "msg:0:blk:1", value: false },
    ]);
  });

  it("clicking checked thinking toggle emits value=null to clear every block's override", () => {
    const onOverride = vi.fn();
    const messages = [thinkingMessage(2)];
    const overrides: Override[] = [
      { kind: "message_block_toggle", target: "msg:0:blk:0", value: false },
      { kind: "message_block_toggle", target: "msg:0:blk:1", value: false },
    ];
    render(<GlobalSection messages={messages} overrides={overrides} onOverride={onOverride} />);

    fireEvent.click(screen.getByRole("switch", { name: "Strip all thinking blocks" }));

    expect(onOverride).toHaveBeenCalledWith([
      { kind: "message_block_toggle", target: "msg:0:blk:0", value: null },
      { kind: "message_block_toggle", target: "msg:0:blk:1", value: null },
    ]);
  });

  it("clicking tool-calls toggle emits overrides for BOTH tool_use AND tool_result halves", () => {
    const onOverride = vi.fn();
    const messages = toolMessages(1);
    render(<GlobalSection messages={messages} overrides={[]} onOverride={onOverride} />);

    fireEvent.click(screen.getByRole("switch", { name: "Strip all tool calls" }));

    // Must include both halves of the pair: msg:0 holds the tool_use,
    // msg:1 holds the tool_result. Emitting only one half would leave
    // an orphan and the Anthropic API would reject the curated payload.
    expect(onOverride).toHaveBeenCalledWith([
      { kind: "message_block_toggle", target: "msg:0:blk:0", value: false },
      { kind: "message_block_toggle", target: "msg:1:blk:0", value: false },
    ]);
  });

  it("disabled when no matching blocks exist, and click is a no-op", () => {
    const onOverride = vi.fn();
    render(<GlobalSection messages={[]} overrides={[]} onOverride={onOverride} />);

    const thinkingBtn = screen.getByRole("switch", { name: "Strip all thinking blocks" });
    const toolBtn = screen.getByRole("switch", { name: "Strip all tool calls" });
    expect(thinkingBtn.hasAttribute("disabled")).toBe(true);
    expect(toolBtn.hasAttribute("disabled")).toBe(true);

    fireEvent.click(thinkingBtn);
    fireEvent.click(toolBtn);
    expect(onOverride).not.toHaveBeenCalled();
  });
});
