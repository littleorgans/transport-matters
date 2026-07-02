import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useUIStore } from "../stores/uiStore";
import { useExchangeStream } from "./useExchangeStream";
import { fireSSE, makePausedFlow, makeWrapper } from "./useExchangeStream.testSupport";

describe("useExchangeStream paused_tokens follow-up", () => {
  it("attaches tokens_before to the matching paused flow", () => {
    renderHook(() => useExchangeStream({ runId: "run-current" }), {
      wrapper: makeWrapper().wrapper,
    });

    useUIStore.setState({
      pausedFlow: makePausedFlow("flow-T"),
    });

    fireSSE({ type: "paused_tokens", flow_id: "flow-T", tokens_before: 4321 });

    expect(useUIStore.getState().pausedFlow?.tokens_before).toBe(4321);
  });

  it("ignores paused_tokens for a flow that no longer matches the pause state", () => {
    renderHook(() => useExchangeStream({ runId: "run-current" }), {
      wrapper: makeWrapper().wrapper,
    });

    useUIStore.setState({
      pausedFlow: makePausedFlow("flow-CURRENT"),
    });

    fireSSE({ type: "paused_tokens", flow_id: "flow-STALE", tokens_before: 999 });

    // Current pause unchanged; no leak from the stale flow's count
    expect(useUIStore.getState().pausedFlow?.flow_id).toBe("flow-CURRENT");
    expect(useUIStore.getState().pausedFlow?.tokens_before).toBeNull();
  });

  it("ignores paused_tokens when no flow is paused at all", () => {
    renderHook(() => useExchangeStream({ runId: "run-current" }), {
      wrapper: makeWrapper().wrapper,
    });

    useUIStore.setState({ pausedFlow: null });

    fireSSE({ type: "paused_tokens", flow_id: "flow-GONE", tokens_before: 1 });

    expect(useUIStore.getState().pausedFlow).toBeNull();
  });

  it("paused event preserves tokens_before when provided", () => {
    renderHook(() => useExchangeStream({ runId: "run-current" }), {
      wrapper: makeWrapper().wrapper,
    });

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
    renderHook(() => useExchangeStream({ runId: "run-current" }), {
      wrapper: makeWrapper().wrapper,
    });

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
    renderHook(() => useExchangeStream({ runId: "run-current" }), {
      wrapper: makeWrapper().wrapper,
    });

    fireSSE({
      type: "paused",
      flow_id: "flow-TRACKED",
      transport: "http",
      run_id: "run-1",
      track_id: "agent-1",
      parent_track_id: "run-1",
      track_display_name: "backend-engineer",
      track_role: "subagent",
      spawn_anchor: {
        track_spawn_exchange_id: "exchange-parent-1",
        track_spawn_tool_use_id: "toolu_child",
        track_spawn_order: 0,
      },
      paused_at_ms: 1000,
      ir: { tools: [], system: [], messages: [] },
    });

    expect(useUIStore.getState().pausedFlow).toMatchObject({
      run_id: "run-1",
      track_id: "agent-1",
      parent_track_id: "run-1",
      track_display_name: "backend-engineer",
      track_role: "subagent",
      spawn_anchor: {
        track_spawn_exchange_id: "exchange-parent-1",
        track_spawn_tool_use_id: "toolu_child",
        track_spawn_order: 0,
      },
    });
  });

  it("paused event without tokens_before defaults to null", () => {
    renderHook(() => useExchangeStream({ runId: "run-current" }), {
      wrapper: makeWrapper().wrapper,
    });

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
