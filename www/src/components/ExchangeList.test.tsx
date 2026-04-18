import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { IndexEntry } from "../types";
import { ExchangeList } from "./ExchangeList";

function makeEntry(overrides: Partial<IndexEntry> = {}): IndexEntry {
  return {
    id: "test-001",
    ts: new Date().toISOString(),
    provider: "anthropic",
    model: "anthropic/claude-sonnet-4-20250514",
    path: "exchanges/test/",
    req: {
      system_parts: 1,
      system_chars: 100,
      tools_count: 3,
      tools_chars: 500,
      messages_count: 2,
      messages_chars: 200,
      total_chars: 800,
    },
    res: {
      stop_reason: "end_turn",
      input_tokens: 100,
      output_tokens: 50,
      cache_creation_input_tokens: 0,
      cache_read_input_tokens: 0,
      text_chars: 200,
      tool_calls: 0,
    },
    pipeline: null,
    mutated_manually: false,
    ...overrides,
  };
}

describe("ExchangeList", () => {
  it("renders exchange entries", () => {
    const entries = [
      makeEntry({ id: "a", model: "anthropic/claude-sonnet-4-20250514" }),
      makeEntry({ id: "b", model: "anthropic/claude-haiku-4-20250506" }),
    ];

    render(
      <ExchangeList
        exchanges={entries}
        currentRunId="run-current"
        includeHistory={false}
        onIncludeHistoryChange={() => {}}
        selectedId={null}
        onSelect={() => {}}
      />,
    );

    expect(screen.getByText("claude-sonnet-4-20250514")).toBeInTheDocument();
    expect(screen.getByText("claude-haiku-4-20250506")).toBeInTheDocument();
  });

  it("calls onSelect when a row is clicked", () => {
    const onSelect = vi.fn();
    const entries = [makeEntry({ id: "click-me" })];

    render(
      <ExchangeList
        exchanges={entries}
        currentRunId="run-current"
        includeHistory={false}
        onIncludeHistoryChange={() => {}}
        selectedId={null}
        onSelect={onSelect}
      />,
    );

    fireEvent.click(screen.getByText("claude-sonnet-4-20250514"));
    expect(onSelect).toHaveBeenCalledWith("click-me");
  });

  it("shows empty state when no exchanges", () => {
    render(
      <ExchangeList
        exchanges={[]}
        currentRunId="run-current"
        includeHistory={false}
        onIncludeHistoryChange={() => {}}
        selectedId={null}
        onSelect={() => {}}
      />,
    );

    expect(screen.getByText("Waiting for traffic")).toBeInTheDocument();
  });

  it("scrolls the list when mounted with a selection", async () => {
    // Smoke test: the effect requests a scroll via Element#scrollTo
    // (which jsdom doesn't implement natively). We assert only that
    // the API is invoked — the computed offset depends on layout and
    // is exercised in real browsers, not jsdom.
    const entries = Array.from({ length: 50 }, (_, i) =>
      makeEntry({ id: `row-${i}`, model: `anthropic/model-${i}` }),
    );
    const scrollToImpl = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      value: scrollToImpl,
      writable: true,
      configurable: true,
    });

    render(
      <ExchangeList
        exchanges={entries}
        currentRunId="run-current"
        includeHistory={false}
        onIncludeHistoryChange={() => {}}
        selectedId="row-42"
        onSelect={() => {}}
      />,
    );

    // Scroll is queued via requestAnimationFrame.
    await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));

    expect(scrollToImpl).toHaveBeenCalled();
  });

  it("re-scrolls when a hidden selection becomes visible again", async () => {
    const entries = Array.from({ length: 50 }, (_, i) =>
      makeEntry({ id: `row-${i}`, model: `anthropic/model-${i}` }),
    );
    const scrollToImpl = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      value: scrollToImpl,
      writable: true,
      configurable: true,
    });

    const { rerender } = render(
      <ExchangeList
        exchanges={entries}
        currentRunId="run-current"
        includeHistory
        onIncludeHistoryChange={() => {}}
        selectedId="row-42"
        onSelect={() => {}}
      />,
    );

    await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
    const initialScrollCalls = scrollToImpl.mock.calls.length;
    expect(initialScrollCalls).toBeGreaterThan(0);

    rerender(
      <ExchangeList
        exchanges={entries.filter((entry) => entry.id !== "row-42")}
        currentRunId="run-current"
        includeHistory={false}
        onIncludeHistoryChange={() => {}}
        selectedId="row-42"
        onSelect={() => {}}
      />,
    );

    rerender(
      <ExchangeList
        exchanges={entries}
        currentRunId="run-current"
        includeHistory
        onIncludeHistoryChange={() => {}}
        selectedId="row-42"
        onSelect={() => {}}
      />,
    );

    await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
    expect(scrollToImpl.mock.calls.length).toBeGreaterThan(initialScrollCalls);
  });

  it("marks exchanges from prior runs when history is enabled", () => {
    render(
      <ExchangeList
        exchanges={[makeEntry({ id: "history-1", run_id: "run-old" })]}
        currentRunId="run-current"
        includeHistory
        onIncludeHistoryChange={() => {}}
        selectedId={null}
        onSelect={() => {}}
      />,
    );

    expect(screen.getByText("prior run")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Show prior runs" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });
});
