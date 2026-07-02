import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "@testing-library/react";
import type { PausedFlow } from "@tm/core/types/exchanges";
import type { ReactNode } from "react";
import { beforeEach, vi } from "vitest";
import { useUIStore } from "../stores/uiStore";

let mockSource: {
  url: string;
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
      constructor(readonly url: string) {
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

export function makePausedFlow(flowId: string): PausedFlow {
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

export function fireSSE(data: Record<string, unknown>) {
  act(() => {
    mockSource?.onmessage?.(new MessageEvent("message", { data: JSON.stringify(data) }));
  });
}

export function getMockSource() {
  if (!mockSource) throw new Error("EventSource has not been constructed");
  return mockSource;
}

export function makeWrapper() {
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
