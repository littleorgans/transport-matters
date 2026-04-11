import { beforeEach, describe, expect, it } from "vitest";
import type { PausedFlow } from "../types";
import { useUIStore } from "./uiStore";

const mockPausedFlow: PausedFlow = {
  flow_id: "test-flow-id",
  ir: {} as PausedFlow["ir"],
  audit: null,
  paused_at_ms: 1000,
};

beforeEach(() => {
  useUIStore.setState({ pausedFlow: null, selectedId: null, activeTab: "log" });
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
      // Simulate BreakpointEditor calling onResolved after forward/drop
      onResolved();
      expect(useUIStore.getState().pausedFlow).toBeNull();
    });
  });

  describe("navigation", () => {
    it("setSelectedId updates selectedId", () => {
      useUIStore.getState().setSelectedId("exchange-123");
      expect(useUIStore.getState().selectedId).toBe("exchange-123");
    });

    it("setActiveTab switches tabs", () => {
      useUIStore.getState().setActiveTab("rules");
      expect(useUIStore.getState().activeTab).toBe("rules");
    });
  });
});
