import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
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
  it("onChange called exactly once per toggle under StrictMode — no side-effect-in-updater double-fire", () => {
    const onChange = vi.fn();

    render(
      <React.StrictMode>
        <MessagesSection messages={messages} onChange={onChange} />
      </React.StrictMode>,
    );

    const toggles = screen.getAllByRole("switch");
    const firstToggle = toggles[0];
    if (firstToggle) {
      fireEvent.click(firstToggle);
    }

    // With the bug: StrictMode double-invokes the updater → onChange fires twice.
    // After the fix: onChange fires exactly once.
    expect(onChange).toHaveBeenCalledTimes(1);
  });
});
