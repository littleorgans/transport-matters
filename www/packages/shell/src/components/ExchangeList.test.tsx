import { fireEvent, render, screen, within } from "@testing-library/react";
import { act } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useTurnContent } from "../hooks/useTurnContent";
import type { IndexEntry } from "../types";
import { legacyClaudeRes, makeEntry } from "./__test-utils__/exchangeList";
import { ExchangeListWithTrackTree as ExchangeList } from "./__test-utils__/exchangeListHarness";

const turnContentById = vi.hoisted(() => new Map<string, unknown>());

vi.mock("../hooks/useTurnContent", () => ({
  useTurnContent: vi.fn(
    (_runId: string | null, id: string) =>
      turnContentById.get(id) ?? { data: undefined, isLoading: false },
  ),
}));

beforeEach(() => {
  turnContentById.clear();
  vi.mocked(useTurnContent).mockClear();
});

function renderExchangeList(exchanges: IndexEntry[]) {
  return render(
    <ExchangeList
      exchanges={exchanges}
      currentRunId="run-current"
      includeHistory={false}
      onIncludeHistoryChange={() => {}}
      selectedId={null}
      onSelect={() => {}}
    />,
  );
}

function exchangeCardFrame(row: HTMLElement): HTMLElement {
  const frame = row.firstElementChild;
  expect(frame).toBeInstanceOf(HTMLElement);
  return frame as HTMLElement;
}

function expectWaitingTransportVisual(entryId: string): HTMLElement {
  const row = screen.getByTestId(`exchange-row-${entryId}`);
  expect(exchangeCardFrame(row)).toHaveClass("border-amber/45");
  expect(row.querySelector(".transport-scan")).toBeInTheDocument();
  expect(row.querySelectorAll(".token-segment")).toHaveLength(10);
  expect(screen.getByTestId(`exchange-token-activity-${entryId}`)).toHaveClass("w-full");
  expect(screen.queryByTestId(`exchange-primary-metric-${entryId}`)).not.toBeInTheDocument();
  return row;
}

function expectSettledTransportVisual(entryId: string): HTMLElement {
  const row = screen.getByTestId(`exchange-row-${entryId}`);
  expect(exchangeCardFrame(row)).not.toHaveClass("border-amber/45");
  expect(row.querySelector(".transport-scan")).not.toBeInTheDocument();
  return row;
}

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
      "Exchange metrics: Input: 100, Output: 50, Total: 100",
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

  it("renders Claude strip as INPUT / OUTPUT / TOTAL", () => {
    const requestShape = {
      system_parts: 1,
      system_chars: 10_000,
      tools_count: 8,
      tools_chars: 40_000,
      messages_count: 8,
      messages_chars: 53_781,
      total_chars: 103_781,
    };

    renderExchangeList([
      makeEntry({ id: "claude-pending", req: requestShape, res: null }),
      makeEntry({
        id: "claude-settled",
        req: requestShape,
        res: {
          stop_reason: "end_turn",
          input_tokens: 14_829,
          output_tokens: 664,
          cache_creation_input_tokens: 9_030,
          cache_read_input_tokens: 13_495,
          text_chars: 401,
          tool_calls: 0,
        },
      }),
    ]);

    expect(screen.getByTestId("exchange-metrics-claude-pending")).toHaveTextContent(
      "Exchange metrics: Input: —, Output: —, Total: —",
    );
    expect(screen.getByTestId("exchange-metrics-claude-pending")).not.toHaveTextContent("103,781");
    expect(screen.getByTestId("exchange-metrics-claude-settled")).toHaveTextContent(
      "Exchange metrics: Input: 14,829, Output: 664, Total: 37,354",
    );
  });

  it("ticks the pending Claude elapsed counter every second", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-04-26T00:00:00.000Z"));
    try {
      renderExchangeList([
        makeEntry({ id: "claude-pending-tick", ts: "2026-04-26T00:00:00.000Z", res: null }),
      ]);

      expect(screen.getByTestId("exchange-time-claude-pending-tick")).toHaveTextContent("0s");

      act(() => {
        vi.advanceTimersByTime(5_000);
      });

      expect(screen.getByTestId("exchange-time-claude-pending-tick")).toHaveTextContent("5s");
    } finally {
      vi.useRealTimers();
    }
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
    expect(row).toHaveClass("min-h-[250px]");
    expect(row).toHaveTextContent("000");
    const metrics = screen.getByTestId("exchange-metrics-codex-1");
    expect(metrics).toHaveTextContent(
      "Exchange metrics: Input: 18,217, Output: 403, Total: 36,265",
    );
    expect(metrics).not.toHaveTextContent("COMPLETE");
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
      "Exchange metrics: Input: —, Output: —, Total: —",
    );
  });

  it("renders HTTP provisional rows with waiting transport visuals", () => {
    renderExchangeList([makeEntry({ id: "http-pending", res: null })]);

    expectWaitingTransportVisual("http-pending");
  });

  it("renders Codex provisional rows with the same waiting transport visuals", () => {
    renderExchangeList([
      makeEntry({
        id: "codex-pending",
        provider: "codex",
        model: "codex/gpt-5-codex",
        res: null,
      }),
    ]);

    expectWaitingTransportVisual("codex-pending");
    expect(
      screen.getByTestId("exchange-row-codex-pending").querySelector("[title]"),
    ).toHaveAttribute("title", "request | waiting for Codex transport");
  });

  it("keeps terminal Codex rows out of the res-null waiting fallback", () => {
    renderExchangeList([
      makeEntry({
        id: "codex-completed-null-res",
        provider: "codex",
        model: "codex/gpt-5-codex",
        res: null,
        codex_turn: {
          turn_index: 6,
          message_range_start: 13,
          message_range_end: 18,
          status: "completed",
          terminal_cause: "response_completed",
          stop_reason: "completed",
          text_chars: 98,
          tool_calls: 0,
        },
      }),
    ]);

    expectSettledTransportVisual("codex-completed-null-res");
  });

  it("clears HTTP waiting visuals when the same exchange row receives response stats", () => {
    const exchangeId = "http-transition";
    const { rerender } = renderExchangeList([makeEntry({ id: exchangeId, res: null })]);

    const pendingRow = expectWaitingTransportVisual(exchangeId);
    turnContentById.set(exchangeId, {
      data: { user_text: "request", response_text: "response", stop_reason: "end_turn" },
      isLoading: false,
    });

    rerender(
      <ExchangeList
        exchanges={[makeEntry({ id: exchangeId, res: legacyClaudeRes })]}
        currentRunId="run-current"
        includeHistory={false}
        onIncludeHistoryChange={() => {}}
        selectedId={null}
        onSelect={() => {}}
      />,
    );

    const settledRow = expectSettledTransportVisual(exchangeId);
    expect(settledRow).toBe(pendingRow);
    expect(screen.getByTestId(`exchange-row-${exchangeId}`)).toHaveTextContent("end_turn");
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
      "Exchange metrics: Input: 120, Output: 10, Total: 120",
    );
    expect(screen.queryByText("000")).not.toBeInTheDocument();
  });

  it("renders Claude settled strip as INPUT / OUTPUT / TOTAL", () => {
    renderExchangeList([
      makeEntry({
        id: "settled",
        res: {
          stop_reason: "end_turn",
          input_tokens: 81,
          output_tokens: 51,
          cache_creation_input_tokens: 60_153,
          cache_read_input_tokens: 16_985,
          text_chars: 200,
          tool_calls: 0,
        },
      }),
    ]);
    expect(screen.getByTestId("exchange-metrics-settled")).toHaveTextContent(
      "Exchange metrics: Input: 81, Output: 51, Total: 77,219",
    );
  });

  it("renders Claude pending strip as dashes", () => {
    renderExchangeList([makeEntry({ id: "pending", res: null })]);
    expect(screen.getByTestId("exchange-metrics-pending")).toHaveTextContent(
      "Exchange metrics: Input: —, Output: —, Total: —",
    );
  });

  it("renders lazy prompt and response columns in settled middle row", () => {
    turnContentById.set("with-preview", {
      data: {
        user_text: "write me a parser",
        response_text: "here is the parser",
        stop_reason: "end_turn",
      },
      isLoading: false,
    });

    renderExchangeList([
      makeEntry({
        id: "with-preview",
        res: legacyClaudeRes,
      }),
    ]);
    const row = screen.getByTestId("exchange-row-with-preview");
    const previewGrid = row.querySelector(".grid-cols-2");
    expect(useTurnContent).toHaveBeenCalledWith("run-current", "with-preview");
    expect(previewGrid).toBeInTheDocument();
    expect(previewGrid?.firstElementChild).toHaveClass("border-r", "border-edge");
    expect(previewGrid?.firstElementChild).toHaveTextContent("write me a parser");
    expect(previewGrid?.firstElementChild).not.toHaveTextContent("end_turn");
    expect(previewGrid?.lastElementChild).toHaveTextContent("here is the parser");
    expect(previewGrid?.lastElementChild).toHaveTextContent("end_turn");
  });

  it("renders lazy response stop reason when response text is absent", () => {
    turnContentById.set("null-response-preview", {
      data: {
        user_text: "write me a parser",
        response_text: null,
        stop_reason: "end_turn",
      },
      isLoading: false,
    });

    renderExchangeList([
      makeEntry({
        id: "null-response-preview",
        res: legacyClaudeRes,
      }),
    ]);

    const row = screen.getByTestId("exchange-row-null-response-preview");
    const previewGrid = row.querySelector(".grid-cols-2");
    expect(previewGrid?.firstElementChild).toHaveTextContent("write me a parser");
    expect(previewGrid?.firstElementChild).not.toHaveTextContent("end_turn");
    expect(previewGrid?.lastElementChild).toHaveTextContent("—");
    expect(previewGrid?.lastElementChild).toHaveTextContent("end_turn");
  });

  it("renders loading placeholders while lazy turn content is loading", () => {
    turnContentById.set("loading-preview", { data: undefined, isLoading: true });

    renderExchangeList([
      makeEntry({
        id: "loading-preview",
        res: legacyClaudeRes,
      }),
    ]);

    const row = screen.getByTestId("exchange-row-loading-preview");
    expect(within(row).getAllByText("\u2026")).toHaveLength(2);
  });

  it("pending card shows no prompt preview and skips lazy content fetch", () => {
    renderExchangeList([makeEntry({ id: "pending-no-preview", res: null })]);
    expect(screen.queryByText("write me")).not.toBeInTheDocument();
    expect(screen.getByTestId("exchange-token-activity-pending-no-preview")).toBeInTheDocument();
    expect(useTurnContent).not.toHaveBeenCalled();
  });
});
