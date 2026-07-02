import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Message, Override } from "../../types";
import { MessagesSection } from "./MessagesSection";

const messages: Message[] = [
  {
    role: "user",
    content: [
      { type: "text", text: "Hello" },
      { type: "text", text: "World" },
    ],
  },
];

describe("MessagesSection", () => {
  it("block toggle calls onOverride with message_block_toggle", () => {
    const onOverride = vi.fn();

    render(<MessagesSection messages={messages} overrides={[]} onOverride={onOverride} />);

    const toggles = screen.getAllByRole("switch");
    // All toggles are block toggles now that the "strip thinking" UI is gone
    const blockToggle = toggles[0];
    if (blockToggle) {
      fireEvent.click(blockToggle);
    }

    expect(onOverride).toHaveBeenCalledWith([
      { kind: "message_block_toggle", target: "msg:0:blk:0", value: false },
    ]);
  });

  it("toggled-off block re-toggle sends null to remove override", () => {
    const onOverride = vi.fn();

    render(
      <MessagesSection
        messages={messages}
        overrides={[{ kind: "message_block_toggle", target: "msg:0:blk:0", value: false }]}
        onOverride={onOverride}
      />,
    );

    const toggles = screen.getAllByRole("switch");
    // Block 0 should be unchecked due to override
    const blockToggle = toggles[0];
    if (blockToggle) {
      expect(blockToggle.getAttribute("aria-checked")).toBe("false");
      fireEvent.click(blockToggle);
    }

    expect(onOverride).toHaveBeenCalledWith([
      { kind: "message_block_toggle", target: "msg:0:blk:0", value: null },
    ]);
  });
});

describe("MessagesSection: tool_use / tool_result tandem toggle", () => {
  // Anthropic rejects orphan tool blocks with `unexpected tool_use_id
  // found in tool_result blocks`. The view layer keeps the pair in
  // tandem so a single click moves both halves and the orphan state
  // is unreachable by hand. The backend sanitize pass is the safety
  // net, but driving the pair from the UI keeps the audit honest:
  // the user's intent ("disable this exchange") shows up as one
  // override per side, not as a half-action plus a silent cleanup.

  function pairedMessages(): Message[] {
    return [
      {
        role: "assistant",
        content: [{ type: "tool_use", id: "tu-1", name: "bash", input: { cmd: "ls" } }],
      },
      {
        role: "user",
        content: [
          {
            type: "tool_result",
            tool_use_id: "tu-1",
            content: [{ type: "text", text: "ok" }],
            is_error: false,
          },
        ],
      },
    ];
  }

  it("toggling a tool_use OFF emits twin message_block_toggle for the matching tool_result", () => {
    const onOverride = vi.fn();
    render(<MessagesSection messages={pairedMessages()} overrides={[]} onOverride={onOverride} />);

    fireEvent.click(screen.getByRole("switch", { name: "Toggle tool_use block" }));

    // The wrapper appends twins after walking the original batch, so
    // the trigger comes first and the synthesised twin follows. Order
    // is deterministic; assert exactly to catch accidental duplication.
    expect(onOverride).toHaveBeenCalledTimes(1);
    expect(onOverride).toHaveBeenCalledWith([
      { kind: "message_block_toggle", target: "msg:0:blk:0", value: false },
      { kind: "message_block_toggle", target: "msg:1:blk:0", value: false },
    ]);
  });

  it("toggling a tool_result OFF emits twin message_block_toggle for the matching tool_use", () => {
    const onOverride = vi.fn();
    render(<MessagesSection messages={pairedMessages()} overrides={[]} onOverride={onOverride} />);

    fireEvent.click(screen.getByRole("switch", { name: "Toggle tool_result block" }));

    expect(onOverride).toHaveBeenCalledWith([
      { kind: "message_block_toggle", target: "msg:1:blk:0", value: false },
      { kind: "message_block_toggle", target: "msg:0:blk:0", value: false },
    ]);
  });

  it("toggling a paired block back ON emits twin clear (value: null) for the partner", () => {
    // Both halves currently disabled. Clicking the tool_use back ON
    // sends value: null to drop its toggle override; the wrapper must
    // mirror the same null on the tool_result so both halves become
    // active in lockstep.
    const onOverride = vi.fn();
    const overrides: Override[] = [
      { kind: "message_block_toggle", target: "msg:0:blk:0", value: false },
      { kind: "message_block_toggle", target: "msg:1:blk:0", value: false },
    ];
    render(
      <MessagesSection messages={pairedMessages()} overrides={overrides} onOverride={onOverride} />,
    );

    fireEvent.click(screen.getByRole("switch", { name: "Toggle tool_use block" }));

    expect(onOverride).toHaveBeenCalledWith([
      { kind: "message_block_toggle", target: "msg:0:blk:0", value: null },
      { kind: "message_block_toggle", target: "msg:1:blk:0", value: null },
    ]);
  });

  it("a tool_use whose tool_result is missing has no pair to move", () => {
    // Asymmetric input (orphan tool_use already present). The wrapper
    // can only twin pairs whose other half is visible; the orphan
    // toggle goes through alone and the backend sanitize pass cleans
    // the residue.
    const onOverride = vi.fn();
    const orphanMessages: Message[] = [
      {
        role: "assistant",
        content: [{ type: "tool_use", id: "tu-orphan", name: "bash", input: {} }],
      },
    ];
    render(<MessagesSection messages={orphanMessages} overrides={[]} onOverride={onOverride} />);

    fireEvent.click(screen.getByRole("switch", { name: "Toggle tool_use block" }));

    expect(onOverride).toHaveBeenCalledWith([
      { kind: "message_block_toggle", target: "msg:0:blk:0", value: false },
    ]);
  });
});

describe("MessagesSection: readOnly mode", () => {
  // The Inspect tab renders MessagesSection with synthesised overrides
  // to mirror the curated payload. The interactive controls must sit
  // out so the reader can't accidentally flip a historical record, and
  // the modified dot must still surface so edits are visible at a glance.
  it("hides Toggle switches and surfaces the modified dot for edited blocks", () => {
    const overrides: Override[] = [{ kind: "message_text", target: "msg:0:blk:0", value: "HELLO" }];
    const { container } = render(
      <MessagesSection messages={messages} overrides={overrides} readOnly />,
    );

    // No interactive switches when readOnly — the Toggle should be absent
    // from both MessageCard (only BlockRow mounts it) and BlockRow itself.
    expect(screen.queryAllByRole("switch")).toHaveLength(0);

    // Modified dot is surfaced: CompositeEditableRow's amber 1x1 pill.
    const modifiedDots = container.querySelectorAll(".bg-amber");
    expect(modifiedDots.length).toBeGreaterThan(0);
  });
});
