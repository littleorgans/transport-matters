import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { legacyClaudeRes, makeEntry } from "./__test-utils__/exchangeList";
import { ExchangeList } from "./ExchangeList";

describe("ExchangeList — row behavior", () => {
  it("numbers Claude exchange turns within each track", () => {
    const { unmount } = render(
      <ExchangeList
        exchanges={[
          makeEntry({
            id: "parent-1",
            run_id: "run-1",
            track_id: "run-1",
            track_role: "parent",
            res: legacyClaudeRes,
            ts: "2026-04-26T00:00:00.000Z",
          }),
          makeEntry({
            id: "parent-2",
            run_id: "run-1",
            track_id: "run-1",
            track_role: "parent",
            ts: "2026-04-26T00:01:00.000Z",
          }),
        ]}
        currentRunId="run-1"
        includeHistory={false}
        onIncludeHistoryChange={() => {}}
        selectedId={null}
        onSelect={() => {}}
      />,
    );

    expect(screen.getByTestId("exchange-row-parent-1")).toHaveTextContent("001");
    expect(screen.getByTestId("exchange-row-parent-2")).toHaveTextContent("002");
    expect(screen.getByTestId("exchange-metrics-parent-1")).toHaveTextContent(
      "Exchange metrics: Tools: 0, Text: 200 chars, Msgs: 2",
    );

    unmount();

    render(
      <ExchangeList
        exchanges={[
          makeEntry({
            id: "child-1",
            run_id: "run-1",
            track_id: "toolu_turn_sequence",
            parent_track_id: "run-1",
            track_display_name: "researcher",
            track_role: "subagent",
            ts: "2026-04-26T00:02:00.000Z",
          }),
          makeEntry({
            id: "child-2",
            run_id: "run-1",
            track_id: "toolu_turn_sequence",
            parent_track_id: "run-1",
            track_display_name: "researcher",
            track_role: "subagent",
            ts: "2026-04-26T00:03:00.000Z",
          }),
        ]}
        currentRunId="run-1"
        includeHistory={false}
        onIncludeHistoryChange={() => {}}
        selectedId={null}
        onSelect={() => {}}
      />,
    );

    expect(screen.getByTestId("exchange-row-child-1")).toHaveTextContent("001");
    expect(screen.getByTestId("exchange-row-child-2")).toHaveTextContent("002");
  });

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

  it("does not move the list when selection changes", async () => {
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
        includeHistory={false}
        onIncludeHistoryChange={() => {}}
        selectedId={null}
        onSelect={() => {}}
      />,
    );

    await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
    scrollToImpl.mockClear();

    rerender(
      <ExchangeList
        exchanges={entries}
        currentRunId="run-current"
        includeHistory={false}
        onIncludeHistoryChange={() => {}}
        selectedId="row-42"
        onSelect={() => {}}
      />,
    );

    await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));

    expect(scrollToImpl).not.toHaveBeenCalled();
  });

  it("does not re-scroll when a hidden selection becomes visible again", async () => {
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
    scrollToImpl.mockClear();

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
    expect(scrollToImpl).not.toHaveBeenCalled();
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

    expect(screen.getByText("prior")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Show prior runs" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("keeps Codex list rows aligned with the shared tools and token summary", () => {
    render(
      <ExchangeList
        exchanges={[
          makeEntry({
            id: "codex-1",
            provider: "codex",
            model: "codex/gpt-5-codex",
            req: {
              system_parts: 0,
              system_chars: 0,
              tools_count: 2,
              tools_chars: 0,
              messages_count: 1,
              messages_chars: 40,
              total_chars: 40,
            },
            res: {
              stop_reason: "completed",
              input_tokens: 18217,
              output_tokens: 403,
              cache_creation_input_tokens: 0,
              cache_read_input_tokens: 18048,
              text_chars: 321,
              tool_calls: 2,
            },
            codex_turn: {
              turn_index: 0,
              message_range_start: 0,
              message_range_end: 3,
              status: "completed",
              terminal_cause: "response_completed",
              stop_reason: "completed",
              text_chars: 321,
              tool_calls: 2,
            },
          }),
        ]}
        currentRunId="run-current"
        includeHistory={false}
        onIncludeHistoryChange={() => {}}
        selectedId={null}
        onSelect={() => {}}
      />,
    );

    const row = screen.getByText("gpt-5-codex").closest("button");
    expect(row).toHaveClass("min-h-[212px]");
    expect(row).toHaveTextContent("000");
    const metrics = screen.getByTestId("exchange-metrics-codex-1");
    expect(metrics).toHaveTextContent("Exchange metrics: Tools: 2, Text: 321 chars, Frames: 0->3");
    expect(metrics).not.toHaveTextContent("COMPLETE");
    expect(screen.getByTestId("exchange-primary-metric-codex-1")).toHaveTextContent("36,265");
    expect(screen.getByTestId("exchange-status-codex-1")).toHaveTextContent("COMPLETE");
    expect(screen.getByText("321")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("renders an open Codex row from semantic turn state without response stats", () => {
    render(
      <ExchangeList
        exchanges={[
          makeEntry({
            id: "codex-open",
            provider: "codex",
            model: "codex/gpt-5-codex",
            res: null,
            codex_turn: {
              turn_index: 4,
              message_range_start: 9,
              message_range_end: 10,
              status: "open",
              terminal_cause: null,
              stop_reason: null,
              text_chars: 12,
              tool_calls: 1,
            },
          }),
        ]}
        currentRunId="run-current"
        includeHistory={false}
        onIncludeHistoryChange={() => {}}
        selectedId={null}
        onSelect={() => {}}
      />,
    );

    expect(screen.getByTestId("exchange-row-codex-open")).toHaveTextContent("004");
    expect(screen.queryByTestId("exchange-primary-metric-codex-open")).not.toBeInTheDocument();
    expect(screen.queryByText("Calculating tokens...")).not.toBeInTheDocument();
    expect(screen.queryByText("awaiting transport")).not.toBeInTheDocument();
    expect(screen.getByTestId("exchange-metrics-codex-open")).toHaveTextContent(
      "Exchange metrics: Tools: 1, Text: 12 chars, Frames: 9->10",
    );
    expect(screen.getByTestId("exchange-status-codex-open")).toHaveTextContent("WAITING");
  });

  it("falls back to legacy stop_reason when Codex semantic summary is missing", () => {
    render(
      <ExchangeList
        exchanges={[
          makeEntry({
            id: "codex-legacy",
            provider: "codex",
            model: "codex/gpt-5-codex",
            res: {
              stop_reason: "completed",
              input_tokens: 120,
              output_tokens: 10,
              cache_creation_input_tokens: 0,
              cache_read_input_tokens: 0,
              text_chars: 41,
              tool_calls: 0,
            },
          }),
        ]}
        currentRunId="run-current"
        includeHistory={false}
        onIncludeHistoryChange={() => {}}
        selectedId={null}
        onSelect={() => {}}
      />,
    );

    expect(screen.getByTestId("exchange-metrics-codex-legacy")).toHaveTextContent(
      "Exchange metrics: Tools: 0, Text: 41 chars, Frames: ...",
    );
    expect(screen.getByTestId("exchange-primary-metric-codex-legacy")).toHaveTextContent("120");
    expect(screen.getByTestId("exchange-status-codex-legacy")).toHaveTextContent("COMPLETED");
    expect(screen.queryByText("000")).not.toBeInTheDocument();
  });
});
