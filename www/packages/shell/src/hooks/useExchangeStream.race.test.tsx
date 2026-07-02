import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useUIStore } from "../stores/uiStore";
import { useExchangeStream } from "./useExchangeStream";
import { fireSSE, makePausedFlow, makeWrapper } from "./useExchangeStream.testSupport";

describe("useExchangeStream race condition guard", () => {
  it("clears pausedFlow when forwarding flow matches current pause", () => {
    renderHook(() => useExchangeStream({ runId: "run-current" }), {
      wrapper: makeWrapper().wrapper,
    });

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
    expect(useUIStore.getState().selectedId).toBe("exchange-uuid-1");
  });

  it("preserves new pausedFlow when a different flow paused during forwarding", () => {
    renderHook(() => useExchangeStream({ runId: "run-current" }), {
      wrapper: makeWrapper().wrapper,
    });

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
    renderHook(() => useExchangeStream({ runId: "run-current" }), {
      wrapper: makeWrapper().wrapper,
    });

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
    renderHook(() => useExchangeStream({ runId: "run-current" }), {
      wrapper: makeWrapper().wrapper,
    });

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
