import { beforeEach, describe, expect, it } from "vitest";
import type { PausedFlow } from "../types";
import { useUIStore } from "./uiStore";

const mockPausedFlow: PausedFlow = {
  flow_id: "test-flow-id",
  ir: {} as PausedFlow["ir"],
  original_tools: [],
  original_system: [],
  original_messages: [],
  audit: null,
  paused_at_ms: 1000,
};

beforeEach(() => {
  useUIStore.setState({ pausedFlow: null, selectedId: null });
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
});
