import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useUIStore } from "../stores/uiStore";
import { useExchangeStream } from "./useExchangeStream";
import { fireSSE, makePausedFlow, makeWrapper } from "./useExchangeStream.testSupport";

describe("useExchangeStream forwarding activity", () => {
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
