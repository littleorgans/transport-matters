import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useUIStore } from "../stores/uiStore";
import type { IndexEntry, PausedFlow } from "../types";
import { useExchangeStream } from "./useExchangeStream";

let mockSource: {
  onopen: (() => void) | null;
  onerror: (() => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  close: ReturnType<typeof vi.fn>;
} | null = null;

beforeEach(() => {
  mockSource = null;
  vi.stubGlobal(
    "EventSource",
    class {
      onopen: (() => void) | null = null;
      onerror: (() => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      close = vi.fn();
      constructor() {
        mockSource = this;
      }
    },
  );
  useUIStore.setState({
    selectedId: null,
    pausedFlow: null,
    forwardingFlowId: null,
    forwardingLastActivityAt: null,
  });
});

function makePausedFlow(flowId: string): PausedFlow {
  return {
    flow_id: flowId,
    transport: "http",
    ir: {
      model: "claude-3",
      provider: "anthropic",
      system: [],
      tools: [],
      messages: [],
      sampling: {
        max_tokens: 1024,
        temperature: null,
        top_p: null,
        top_k: null,
        stop_sequences: [],
      },
      metadata: {
        session_id: null,
        device_id: null,
        account_id: null,
        provider_metadata: {},
      },
      stream: false,
      provider_extras: {},
    },
    original_tools: [],
    original_system: [],
    original_messages: [],
    original_sampling: {
      max_tokens: 1024,
      temperature: null,
      top_p: null,
      top_k: null,
      stop_sequences: [],
    },
    original_provider_extras: {},
    audit: null,
    paused_at_ms: Date.now(),
    tokens_before: null,
  };
}

function fireSSE(data: Record<string, unknown>) {
  act(() => {
    mockSource?.onmessage?.(new MessageEvent("message", { data: JSON.stringify(data) }));
  });
}

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return {
    qc,
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    ),
  };
}

describe("useExchangeStream — race condition guard", () => {
  it("clears pausedFlow when forwarding flow matches current pause", () => {
    renderHook(() => useExchangeStream(), { wrapper: makeWrapper().wrapper });

    useUIStore.setState({
      pausedFlow: makePausedFlow("flow-X"),
      forwardingFlowId: "flow-X",
    });

    // exchange id is a UUID distinct from flow_id
    fireSSE({
      type: "exchange",
      id: "exchange-uuid-1",
      flow_id: "flow-X",
      ts: "2026-01-01T00:00:00Z",
      provider: "anthropic",
      model: "claude-3",
      req: { method: "POST" },
    });

    expect(useUIStore.getState().pausedFlow).toBeNull();
    expect(useUIStore.getState().forwardingFlowId).toBeNull();
  });

  it("preserves new pausedFlow when a different flow paused during forwarding", () => {
    renderHook(() => useExchangeStream(), { wrapper: makeWrapper().wrapper });

    // Flow X was forwarded, but flow Y paused in the meantime
    useUIStore.setState({
      pausedFlow: makePausedFlow("flow-Y"),
      forwardingFlowId: "flow-X",
    });

    // Exchange event arrives for the forwarded flow X
    fireSSE({
      type: "exchange",
      id: "exchange-uuid-2",
      flow_id: "flow-X",
      ts: "2026-01-01T00:00:00Z",
      provider: "anthropic",
      model: "claude-3",
      req: { method: "POST" },
    });

    // Flow Y should still be paused
    expect(useUIStore.getState().pausedFlow?.flow_id).toBe("flow-Y");
    // Forwarding state should be cleared
    expect(useUIStore.getState().forwardingFlowId).toBeNull();
  });

  it("does not clear pausedFlow when flow_id does not match forwardingFlowId", () => {
    renderHook(() => useExchangeStream(), { wrapper: makeWrapper().wrapper });

    useUIStore.setState({
      pausedFlow: makePausedFlow("flow-A"),
      forwardingFlowId: "flow-A",
    });

    // Exchange for a different flow
    fireSSE({
      type: "exchange",
      id: "exchange-uuid-3",
      flow_id: "flow-OTHER",
      ts: "2026-01-01T00:00:00Z",
      provider: "anthropic",
      model: "claude-3",
      req: { method: "POST" },
    });

    expect(useUIStore.getState().pausedFlow?.flow_id).toBe("flow-A");
    expect(useUIStore.getState().forwardingFlowId).toBe("flow-A");
  });

  it("does not clear pausedFlow when exchange has no flow_id", () => {
    renderHook(() => useExchangeStream(), { wrapper: makeWrapper().wrapper });

    useUIStore.setState({
      pausedFlow: makePausedFlow("flow-A"),
      forwardingFlowId: "flow-A",
    });

    // Non-breakpoint exchange (no flow_id field)
    fireSSE({
      type: "exchange",
      id: "exchange-uuid-4",
      ts: "2026-01-01T00:00:00Z",
      provider: "anthropic",
      model: "claude-3",
      req: { method: "POST" },
    });

    expect(useUIStore.getState().pausedFlow?.flow_id).toBe("flow-A");
    expect(useUIStore.getState().forwardingFlowId).toBe("flow-A");
  });
});

describe("useExchangeStream — SSE validation", () => {
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

    expect(qc.getQueryData<IndexEntry[]>(["exchanges", false])?.[0]?.id).toBe("exchange-live-new");
    expect(useUIStore.getState().selectedId).toBe("manual-selection");
  });

  it("removes deleted exchanges from the live cache and clears selection", () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );

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
    expect(qc.getQueryData(["exchanges", false])).toEqual([]);
  });

  it("invalidates the matching exchange detail query when an exchange updates", () => {
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
      queryKey: ["exchange", "exchange-live-2"],
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

    const rows = qc.getQueryData<IndexEntry[]>(["exchanges", false]);
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

    const rows = qc.getQueryData<IndexEntry[]>(["exchanges", false]);
    expect(rows?.[0]).toMatchObject({
      run_id: "run-1",
      track_id: "agent-1",
      parent_track_id: "run-1",
      track_display_name: "backend-engineer",
      track_role: "subagent",
    });
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

    const rows = qc.getQueryData<IndexEntry[]>(["exchanges", false]);
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

    const rows = qc.getQueryData<IndexEntry[]>(["exchanges", false]);
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

    let rows = qc.getQueryData<IndexEntry[]>(["exchanges", false]);
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

    rows = qc.getQueryData<IndexEntry[]>(["exchanges", false]);
    expect(rows).toHaveLength(1);
    expect(rows?.[0]?.res?.stop_reason).toBe("failed");
    expect(rows?.[0]?.codex_turn?.status).toBe("failed");
    expect(rows?.[0]?.codex_turn?.message_range_end).toBe(5);
    expect(rows?.[0]?.codex_turn?.tool_calls).toBe(0);
  });
});

describe("useExchangeStream — forwarding activity", () => {
  it("bumps lastActivityAt when any event's flow_id matches forwardingFlowId", () => {
    renderHook(() => useExchangeStream(), { wrapper: makeWrapper().wrapper });

    useUIStore.setState({
      pausedFlow: makePausedFlow("flow-LIVE"),
      forwardingFlowId: "flow-LIVE",
      forwardingLastActivityAt: null,
    });

    // paused_tokens carries a flow_id but does not clear forwarding state,
    // so it's a clean liveness signal to assert against.
    fireSSE({ type: "paused_tokens", flow_id: "flow-LIVE", tokens_before: 500 });

    expect(useUIStore.getState().forwardingLastActivityAt).not.toBeNull();
  });

  it("does not bump lastActivityAt when the event's flow_id does not match", () => {
    renderHook(() => useExchangeStream(), { wrapper: makeWrapper().wrapper });

    useUIStore.setState({
      pausedFlow: makePausedFlow("flow-A"),
      forwardingFlowId: "flow-A",
      forwardingLastActivityAt: null,
    });

    fireSSE({ type: "paused_tokens", flow_id: "flow-OTHER", tokens_before: 1 });

    expect(useUIStore.getState().forwardingLastActivityAt).toBeNull();
  });

  it("does not bump lastActivityAt when nothing is being forwarded", () => {
    renderHook(() => useExchangeStream(), { wrapper: makeWrapper().wrapper });

    useUIStore.setState({
      forwardingFlowId: null,
      forwardingLastActivityAt: null,
    });

    fireSSE({ type: "paused_tokens", flow_id: "flow-ANY", tokens_before: 1 });

    expect(useUIStore.getState().forwardingLastActivityAt).toBeNull();
  });
});

describe("useExchangeStream — paused_tokens follow-up", () => {
  it("attaches tokens_before to the matching paused flow", () => {
    renderHook(() => useExchangeStream(), { wrapper: makeWrapper().wrapper });

    useUIStore.setState({
      pausedFlow: makePausedFlow("flow-T"),
    });

    fireSSE({ type: "paused_tokens", flow_id: "flow-T", tokens_before: 4321 });

    expect(useUIStore.getState().pausedFlow?.tokens_before).toBe(4321);
  });

  it("ignores paused_tokens for a flow that no longer matches the pause state", () => {
    renderHook(() => useExchangeStream(), { wrapper: makeWrapper().wrapper });

    useUIStore.setState({
      pausedFlow: makePausedFlow("flow-CURRENT"),
    });

    fireSSE({ type: "paused_tokens", flow_id: "flow-STALE", tokens_before: 999 });

    // Current pause unchanged — no leak from the stale flow's count
    expect(useUIStore.getState().pausedFlow?.flow_id).toBe("flow-CURRENT");
    expect(useUIStore.getState().pausedFlow?.tokens_before).toBeNull();
  });

  it("ignores paused_tokens when no flow is paused at all", () => {
    renderHook(() => useExchangeStream(), { wrapper: makeWrapper().wrapper });

    useUIStore.setState({ pausedFlow: null });

    fireSSE({ type: "paused_tokens", flow_id: "flow-GONE", tokens_before: 1 });

    expect(useUIStore.getState().pausedFlow).toBeNull();
  });

  it("paused event preserves tokens_before when provided", () => {
    renderHook(() => useExchangeStream(), { wrapper: makeWrapper().wrapper });

    fireSSE({
      type: "paused",
      flow_id: "flow-NEW",
      transport: "websocket",
      paused_at_ms: 1000,
      ir: { tools: [], system: [], messages: [] },
      tokens_before: 7,
    });

    expect(useUIStore.getState().pausedFlow?.tokens_before).toBe(7);
    expect(useUIStore.getState().pausedFlow?.transport).toBe("websocket");
  });

  it("paused websocket event carries the provisional exchange id", () => {
    renderHook(() => useExchangeStream(), { wrapper: makeWrapper().wrapper });

    fireSSE({
      type: "paused",
      flow_id: "flow-CODEX",
      transport: "websocket",
      provisional_exchange_id: "exchange-provisional-9",
      paused_at_ms: 1000,
      ir: { tools: [], system: [], messages: [] },
    });

    expect(useUIStore.getState().pausedFlow?.provisional_exchange_id).toBe(
      "exchange-provisional-9",
    );
  });

  it("paused event carries track scope", () => {
    renderHook(() => useExchangeStream(), { wrapper: makeWrapper().wrapper });

    fireSSE({
      type: "paused",
      flow_id: "flow-TRACKED",
      transport: "http",
      run_id: "run-1",
      track_id: "agent-1",
      parent_track_id: "run-1",
      track_display_name: "backend-engineer",
      track_role: "subagent",
      paused_at_ms: 1000,
      ir: { tools: [], system: [], messages: [] },
    });

    expect(useUIStore.getState().pausedFlow).toMatchObject({
      run_id: "run-1",
      track_id: "agent-1",
      parent_track_id: "run-1",
      track_display_name: "backend-engineer",
      track_role: "subagent",
    });
  });

  it("paused event without tokens_before defaults to null", () => {
    renderHook(() => useExchangeStream(), { wrapper: makeWrapper().wrapper });

    fireSSE({
      type: "paused",
      flow_id: "flow-INITIAL",
      transport: "http",
      paused_at_ms: 1000,
      ir: { tools: [], system: [], messages: [] },
    });

    expect(useUIStore.getState().pausedFlow?.tokens_before).toBeNull();
    expect(useUIStore.getState().pausedFlow?.track_role).toBeNull();
  });
});
