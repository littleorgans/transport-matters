import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import {
  applyExchangeStreamEvent,
  type ExchangeStreamEventContext,
  type StreamSideEffects,
} from "./exchangeStreamEvents";
import { exchangesKey } from "./queryKeys";
import type { IndexEntry } from "./types/exchanges";

function inertSideEffects(): StreamSideEffects {
  return {
    getForwardingFlowId: () => null,
    getPausedFlow: () => null,
    getSelectedId: () => null,
    bumpForwardingActivity: () => {},
    setForwardingFlowId: () => {},
  };
}

function inertContext(runId: string, queryClient: QueryClient): ExchangeStreamEventContext {
  return {
    runId,
    queryClient,
    setPausedFlow: () => {},
    clearPausedFlow: () => {},
    setSelectedId: () => {},
    sideEffects: inertSideEffects(),
  };
}

describe("exchange stream event application", () => {
  it("applies exchange events without a store or a browser stream source", () => {
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
      inertContext("run-current", queryClient),
    );

    expect(queryClient.getQueryData<IndexEntry[]>(exchangesKey("run-current"))?.[0]?.id).toBe(
      "exchange-boundary-1",
    );
  });

  it("routes forwarding reads and effects through the side-effect port", () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const bumped: string[] = [];
    const selected: Array<string | null> = [];
    const context = inertContext("run-current", queryClient);
    context.setSelectedId = (id) => selected.push(id);
    context.sideEffects = {
      ...inertSideEffects(),
      getForwardingFlowId: () => "flow-1",
      bumpForwardingActivity: () => bumped.push("bump"),
    };

    applyExchangeStreamEvent(
      JSON.stringify({
        type: "exchange",
        id: "exchange-boundary-2",
        flow_id: "flow-1",
        ts: "2026-01-01T00:00:00Z",
        provider: "codex",
        model: "gpt-5-codex",
        req: { total_chars: 1 },
      }),
      context,
    );

    expect(bumped).toEqual(["bump"]);
    expect(selected).toEqual(["exchange-boundary-2"]);
  });
});
