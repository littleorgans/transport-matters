import type { PausedFlow } from "@tm/core/types/exchanges";
import { beforeEach, describe, expect, it } from "vitest";
import { useUIStore } from "./uiStore";

const mockPausedFlow: PausedFlow = {
  flow_id: "test-flow-id",
  transport: "http",
  ir: {} as PausedFlow["ir"],
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
  paused_at_ms: 1000,
  tokens_before: null,
};

beforeEach(() => {
  useUIStore.setState({
    pausedFlow: null,
    selectedId: null,
    forwardingFlowId: null,
    forwardingLastActivityAt: null,
  });
});

describe("uiStore", () => {
  describe("pausedFlow", () => {
    it("setPausedFlow stores the flow", () => {
      useUIStore.getState().setPausedFlow(mockPausedFlow);
      expect(useUIStore.getState().pausedFlow?.flow_id).toBe("test-flow-id");
    });

    it("clearPausedFlow sets pausedFlow to null", () => {
      useUIStore.setState({ pausedFlow: mockPausedFlow });
      useUIStore.getState().clearPausedFlow();
      expect(useUIStore.getState().pausedFlow).toBeNull();
    });

    it("clearPausedFlow is the onResolved handler — calling it clears the overlay", () => {
      useUIStore.setState({ pausedFlow: mockPausedFlow });
      const onResolved = useUIStore.getState().clearPausedFlow;
      onResolved();
      expect(useUIStore.getState().pausedFlow).toBeNull();
    });
  });

  describe("navigation", () => {
    it("setSelectedId updates selectedId", () => {
      useUIStore.getState().setSelectedId("exchange-123");
      expect(useUIStore.getState().selectedId).toBe("exchange-123");
    });
  });

  describe("forwarding activity", () => {
    it("bumpForwardingActivity stamps lastActivityAt with a Date.now() value", () => {
      const before = Date.now();
      useUIStore.getState().bumpForwardingActivity();
      const stamped = useUIStore.getState().forwardingLastActivityAt;

      expect(stamped).not.toBeNull();
      expect(stamped).toBeGreaterThanOrEqual(before);
    });

    it("bumpForwardingActivity produces a fresh timestamp on each call", async () => {
      useUIStore.getState().bumpForwardingActivity();
      const first = useUIStore.getState().forwardingLastActivityAt;
      // `Date.now()` is ms-resolution; yield the event loop to guarantee
      // the second stamp lands on a different tick.
      await new Promise((r) => setTimeout(r, 2));
      useUIStore.getState().bumpForwardingActivity();
      const second = useUIStore.getState().forwardingLastActivityAt;

      expect(first).not.toBeNull();
      expect(second).not.toBeNull();
      expect(second as number).toBeGreaterThan(first as number);
    });

    it("setForwardingFlowId(null) resets lastActivityAt alongside the id", () => {
      useUIStore.setState({
        forwardingFlowId: "flow-abc",
        forwardingLastActivityAt: Date.now(),
      });
      useUIStore.getState().setForwardingFlowId(null);

      expect(useUIStore.getState().forwardingFlowId).toBeNull();
      expect(useUIStore.getState().forwardingLastActivityAt).toBeNull();
    });

    it("setForwardingFlowId(id) does not stamp lastActivityAt — only events do", () => {
      useUIStore.getState().setForwardingFlowId("flow-abc");

      expect(useUIStore.getState().forwardingFlowId).toBe("flow-abc");
      // Starting a forward doesn't count as activity; the initial
      // silence window is measured by the timer's own setTimeout.
      expect(useUIStore.getState().forwardingLastActivityAt).toBeNull();
    });

    it("clearPausedFlow resets forwardingFlowId and lastActivityAt together", () => {
      useUIStore.setState({
        pausedFlow: mockPausedFlow,
        forwardingFlowId: "flow-abc",
        forwardingLastActivityAt: Date.now(),
      });
      useUIStore.getState().clearPausedFlow();

      expect(useUIStore.getState().pausedFlow).toBeNull();
      expect(useUIStore.getState().forwardingFlowId).toBeNull();
      expect(useUIStore.getState().forwardingLastActivityAt).toBeNull();
    });
  });
});
