import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useUIStore } from "../stores/uiStore";
import type { PausedFlow } from "../types";
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
  });
});

function makePausedFlow(flowId: string): PausedFlow {
  return {
    flow_id: flowId,
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
    audit: null,
    paused_at_ms: Date.now(),
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
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe("useExchangeStream — race condition guard", () => {
  it("clears pausedFlow when forwarding flow matches current pause", () => {
    renderHook(() => useExchangeStream(), { wrapper: makeWrapper() });

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
    renderHook(() => useExchangeStream(), { wrapper: makeWrapper() });

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
    renderHook(() => useExchangeStream(), { wrapper: makeWrapper() });

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
    renderHook(() => useExchangeStream(), { wrapper: makeWrapper() });

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
    renderHook(() => useExchangeStream(), { wrapper: makeWrapper() });

    // Missing req field
    fireSSE({
      type: "exchange",
      id: "flow-Z",
      ts: "2026-01-01T00:00:00Z",
      model: "claude-3",
    });

    expect(useUIStore.getState().selectedId).toBeNull();
  });
});
