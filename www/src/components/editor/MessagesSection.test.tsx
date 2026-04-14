import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Message } from "../../types";
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
