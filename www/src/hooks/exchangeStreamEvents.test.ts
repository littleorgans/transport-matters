import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { useUIStore } from "../stores/uiStore";
import type { IndexEntry } from "../types";
import { applyExchangeStreamEvent } from "./exchangeStreamEvents";

describe("exchange stream event application", () => {
  it("applies exchange events without constructing a browser stream source", () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    applyExchangeStreamEvent(
      JSON.stringify({
        type: "exchange",
        id: "exchange-boundary-1",
        ts: "2026-01-01T00:00:00Z",
        provider: "codex",
        model: "gpt-5-codex",
        req: { total_chars: 1 },
      }),
      {
        queryClient,
        setPausedFlow: useUIStore.getState().setPausedFlow,
        clearPausedFlow: useUIStore.getState().clearPausedFlow,
        setSelectedId: useUIStore.getState().setSelectedId,
      },
    );

    expect(queryClient.getQueryData<IndexEntry[]>(["exchanges", false])?.[0]?.id).toBe(
      "exchange-boundary-1",
    );
  });
});
