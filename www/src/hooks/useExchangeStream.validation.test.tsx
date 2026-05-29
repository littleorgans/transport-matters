import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { exchangeKey, exchangesKey, turnContentKey } from "../lib/queryKeys";
import { useUIStore } from "../stores/uiStore";
import type { IndexEntry } from "../types";
import { useExchangeStream } from "./useExchangeStream";
import { fireSSE, makeWrapper } from "./useExchangeStream.testSupport";

describe("useExchangeStream SSE validation", () => {
  it("ignores exchange events with missing required fields", () => {
    renderHook(() => useExchangeStream(), { wrapper: makeWrapper().wrapper });

    // Missing req field
    fireSSE({
      type: "exchange",
      id: "flow-Z",
      ts: "2026-01-01T00:00:00Z",
      model: "claude-3",
    });

    expect(useUIStore.getState().selectedId).toBeNull();
  });

  it("does not auto select new exchange events", () => {
    const { qc, wrapper } = makeWrapper();
    useUIStore.setState({ selectedId: "manual-selection" });

    renderHook(() => useExchangeStream(), { wrapper });

    fireSSE({
      type: "exchange",
      id: "exchange-live-new",
      ts: "2026-01-01T00:00:00Z",
      provider: "codex",
      model: "gpt-5-codex",
      req: { total_chars: 1 },
    });

    expect(qc.getQueryData<IndexEntry[]>(exchangesKey(false))?.[0]?.id).toBe("exchange-live-new");
    expect(useUIStore.getState().selectedId).toBe("manual-selection");
  });

  it("removes deleted exchanges from the live cache and clears selection", () => {
    const { qc, wrapper } = makeWrapper();
    const removeSpy = vi.spyOn(qc, "removeQueries");

    renderHook(() => useExchangeStream(), { wrapper });

    fireSSE({
      type: "exchange",
      id: "exchange-live-1",
      ts: "2026-01-01T00:00:00Z",
      provider: "codex",
      model: "gpt-5-codex",
      req: { total_chars: 1 },
    });
    useUIStore.setState({ selectedId: "exchange-live-1" });

    fireSSE({ type: "exchange_deleted", id: "exchange-live-1" });

    expect(useUIStore.getState().selectedId).toBeNull();
    expect(qc.getQueryData(exchangesKey(false))).toEqual([]);
    expect(removeSpy).toHaveBeenCalledWith({
      queryKey: turnContentKey("exchange-live-1"),
      exact: true,
    });
  });

  it("invalidates the matching exchange detail and turn-content queries when an exchange updates", () => {
    const { qc, wrapper } = makeWrapper();
    const invalidateSpy = vi.spyOn(qc, "invalidateQueries");

    renderHook(() => useExchangeStream(), { wrapper });

    fireSSE({
      type: "exchange",
      id: "exchange-live-2",
      ts: "2026-01-01T00:00:00Z",
      provider: "codex",
      model: "gpt-5-codex",
      req: { total_chars: 1 },
    });

    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: exchangeKey("exchange-live-2"),
    });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: turnContentKey("exchange-live-2"),
    });
  });

  it("stores Codex turn summaries from exchange events", () => {
    const { qc, wrapper } = makeWrapper();

    renderHook(() => useExchangeStream(), { wrapper });

    fireSSE({
      type: "exchange",
      id: "exchange-live-codex",
      ts: "2026-01-01T00:00:00Z",
      provider: "codex",
      model: "gpt-5-codex",
      req: { total_chars: 1 },
      codex_turn: {
        turn_index: 1,
        message_range_start: 2,
        message_range_end: 4,
        status: "open",
        terminal_cause: null,
        stop_reason: null,
        text_chars: 12,
        tool_calls: 1,
      },
    });

    const rows = qc.getQueryData<IndexEntry[]>(exchangesKey(false));
    expect(rows?.[0]?.codex_turn?.status).toBe("open");
    expect(rows?.[0]?.codex_turn?.message_range_end).toBe(4);
  });

  it("stores track fields from exchange events", () => {
    const { qc, wrapper } = makeWrapper();

    renderHook(() => useExchangeStream(), { wrapper });

    fireSSE({
      type: "exchange",
      id: "exchange-live-track",
      run_id: "run-1",
      track_id: "agent-1",
      parent_track_id: "run-1",
      track_display_name: "backend-engineer",
      track_role: "subagent",
      ts: "2026-01-01T00:00:00Z",
      provider: "codex",
      model: "gpt-5-codex",
      req: { total_chars: 1 },
    });

    const rows = qc.getQueryData<IndexEntry[]>(exchangesKey(false));
    expect(rows?.[0]).toMatchObject({
      run_id: "run-1",
      track_id: "agent-1",
      parent_track_id: "run-1",
      track_display_name: "backend-engineer",
      track_role: "subagent",
    });
  });

  it("preserves nested spawn anchors from live exchange events", () => {
    const { qc, wrapper } = makeWrapper();

    renderHook(() => useExchangeStream(), { wrapper });

    fireSSE({
      type: "exchange",
      id: "exchange-anchored",
      run_id: "run-1",
      track_id: "agent-2",
      parent_track_id: "run-1",
      track_display_name: "researcher",
      track_role: "subagent",
      spawn_anchor: {
        track_spawn_exchange_id: "exchange-parent-7",
        track_spawn_tool_use_id: "toolu_child_a",
        track_spawn_order: 0,
      },
      ts: "2026-01-01T00:00:00Z",
      provider: "anthropic",
      model: "claude-3",
      req: { total_chars: 1 },
    });

    const rows = qc.getQueryData<IndexEntry[]>(exchangesKey(false));
    expect(rows?.[0]).toMatchObject({
      spawn_anchor: {
        track_spawn_exchange_id: "exchange-parent-7",
        track_spawn_tool_use_id: "toolu_child_a",
        track_spawn_order: 0,
      },
    });
  });

  it("propagates nested spawn anchors into the history cache when present", () => {
    const { qc, wrapper } = makeWrapper();
    qc.setQueryData<IndexEntry[]>(exchangesKey(true), []);

    renderHook(() => useExchangeStream(), { wrapper });

    fireSSE({
      type: "exchange",
      id: "exchange-history-anchored",
      run_id: "run-1",
      track_id: "agent-3",
      parent_track_id: "run-1",
      track_role: "subagent",
      spawn_anchor: {
        track_spawn_exchange_id: "exchange-parent-9",
        track_spawn_tool_use_id: "toolu_child_b",
        track_spawn_order: 1,
      },
      ts: "2026-01-01T00:00:00Z",
      provider: "codex",
      model: "gpt-5-codex",
      req: { total_chars: 1 },
    });

    const live = qc.getQueryData<IndexEntry[]>(exchangesKey(false));
    expect(live?.[0]?.spawn_anchor?.track_spawn_tool_use_id).toBe("toolu_child_b");
    const history = qc.getQueryData<IndexEntry[]>(exchangesKey(true));
    expect(history?.[0]).toMatchObject({
      spawn_anchor: {
        track_spawn_exchange_id: "exchange-parent-9",
        track_spawn_tool_use_id: "toolu_child_b",
        track_spawn_order: 1,
      },
    });
  });

  it("defaults spawn anchor to null when the event omits it", () => {
    const { qc, wrapper } = makeWrapper();

    renderHook(() => useExchangeStream(), { wrapper });

    fireSSE({
      type: "exchange",
      id: "exchange-untethered",
      ts: "2026-01-01T00:00:00Z",
      provider: "anthropic",
      model: "claude-3",
      req: { total_chars: 1 },
    });

    const rows = qc.getQueryData<IndexEntry[]>(exchangesKey(false));
    expect(rows?.[0]?.spawn_anchor).toBeNull();
  });

  it("leaves track role null when exchange event omits it", () => {
    const { qc, wrapper } = makeWrapper();

    renderHook(() => useExchangeStream(), { wrapper });

    fireSSE({
      type: "exchange",
      id: "exchange-live-untracked",
      ts: "2026-01-01T00:00:00Z",
      provider: "anthropic",
      model: "claude-3",
      req: { total_chars: 1 },
    });

    const rows = qc.getQueryData<IndexEntry[]>(exchangesKey(false));
    expect(rows?.[0]?.track_role).toBeNull();
  });

  it("drops malformed Codex turn summaries without rejecting the exchange event", () => {
    const { qc, wrapper } = makeWrapper();

    renderHook(() => useExchangeStream(), { wrapper });

    fireSSE({
      type: "exchange",
      id: "exchange-live-codex-malformed",
      ts: "2026-01-01T00:00:00Z",
      provider: "codex",
      model: "gpt-5-codex",
      req: { total_chars: 1 },
      codex_turn: {
        turn_index: 1,
        message_range_start: 2,
        message_range_end: 4,
        status: "paused",
        terminal_cause: null,
        stop_reason: null,
        text_chars: 12,
        tool_calls: 1,
      },
    });

    const rows = qc.getQueryData<IndexEntry[]>(exchangesKey(false));
    expect(rows).toHaveLength(1);
    expect(rows?.[0]?.id).toBe("exchange-live-codex-malformed");
    expect(rows?.[0]?.codex_turn).toBeNull();
  });

  it("keeps a live Codex row in sync across open updates and finalization", () => {
    const { qc, wrapper } = makeWrapper();

    renderHook(() => useExchangeStream(), { wrapper });

    fireSSE({
      type: "exchange",
      id: "exchange-live-codex-sync",
      ts: "2026-01-01T00:00:00Z",
      provider: "codex",
      model: "gpt-5-codex",
      req: { total_chars: 1 },
      codex_turn: {
        turn_index: 1,
        message_range_start: 2,
        message_range_end: 3,
        status: "open",
        terminal_cause: null,
        stop_reason: null,
        text_chars: 5,
        tool_calls: 0,
      },
    });

    fireSSE({
      type: "exchange",
      id: "exchange-live-codex-sync",
      ts: "2026-01-01T00:00:01Z",
      provider: "codex",
      model: "gpt-5-codex",
      req: { total_chars: 1 },
      codex_turn: {
        turn_index: 1,
        message_range_start: 2,
        message_range_end: 4,
        status: "open",
        terminal_cause: null,
        stop_reason: null,
        text_chars: 11,
        tool_calls: 1,
      },
    });

    let rows = qc.getQueryData<IndexEntry[]>(exchangesKey(false));
    expect(rows).toHaveLength(1);
    expect(rows?.[0]?.codex_turn?.status).toBe("open");
    expect(rows?.[0]?.codex_turn?.message_range_end).toBe(4);
    expect(rows?.[0]?.codex_turn?.text_chars).toBe(11);
    expect(rows?.[0]?.codex_turn?.tool_calls).toBe(1);

    fireSSE({
      type: "exchange",
      id: "exchange-live-codex-sync",
      ts: "2026-01-01T00:00:02Z",
      provider: "codex",
      model: "gpt-5-codex",
      req: { total_chars: 1 },
      res: {
        stop_reason: "failed",
        input_tokens: 0,
        output_tokens: 0,
        cache_creation_input_tokens: 0,
        cache_read_input_tokens: 0,
        text_chars: 11,
        tool_calls: 0,
      },
      codex_turn: {
        turn_index: 1,
        message_range_start: 2,
        message_range_end: 5,
        status: "failed",
        terminal_cause: "response_failed",
        stop_reason: "failed",
        text_chars: 11,
        tool_calls: 0,
      },
    });

    rows = qc.getQueryData<IndexEntry[]>(exchangesKey(false));
    expect(rows).toHaveLength(1);
    expect(rows?.[0]?.res?.stop_reason).toBe("failed");
    expect(rows?.[0]?.codex_turn?.status).toBe("failed");
    expect(rows?.[0]?.codex_turn?.message_range_end).toBe(5);
    expect(rows?.[0]?.codex_turn?.tool_calls).toBe(0);
  });

  it("accepts stable subagent tool counts during finalization", () => {
    const { qc, wrapper } = makeWrapper();

    renderHook(() => useExchangeStream(), { wrapper });

    fireSSE({
      type: "exchange",
      id: "exchange-live-subagent",
      run_id: "run-1",
      track_id: "agent-1",
      parent_track_id: "run-1",
      track_role: "subagent",
      ts: "2026-01-01T00:00:01Z",
      provider: "codex",
      model: "gpt-5-codex",
      req: { total_chars: 1 },
      codex_turn: {
        turn_index: 5,
        message_range_start: 0,
        message_range_end: 69,
        status: "open",
        terminal_cause: null,
        stop_reason: null,
        text_chars: 0,
        tool_calls: 1,
      },
    });

    fireSSE({
      type: "exchange",
      id: "exchange-live-subagent",
      run_id: "run-1",
      track_id: "agent-1",
      parent_track_id: "run-1",
      track_role: "subagent",
      ts: "2026-01-01T00:00:02Z",
      provider: "codex",
      model: "gpt-5-codex",
      req: { total_chars: 1 },
      res: {
        stop_reason: "completed",
        input_tokens: 0,
        output_tokens: 0,
        cache_creation_input_tokens: 0,
        cache_read_input_tokens: 0,
        text_chars: 0,
        tool_calls: 0,
      },
      codex_turn: {
        turn_index: 5,
        message_range_start: 0,
        message_range_end: 70,
        status: "completed",
        terminal_cause: "response_completed",
        stop_reason: "completed",
        text_chars: 0,
        tool_calls: 1,
      },
    });

    const rows = qc.getQueryData<IndexEntry[]>(exchangesKey(false));
    expect(rows).toHaveLength(1);
    expect(rows?.[0]?.track_role).toBe("subagent");
    expect(rows?.[0]?.codex_turn?.status).toBe("completed");
    expect(rows?.[0]?.codex_turn?.message_range_end).toBe(70);
    expect(rows?.[0]?.codex_turn?.tool_calls).toBe(1);
  });
});
