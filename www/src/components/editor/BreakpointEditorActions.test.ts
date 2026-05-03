import { describe, expect, it } from "vitest";
import type { PausedFlow } from "../../types";
import { getExchangeDetailQueryKey, getReleasedFlowCompletion } from "./BreakpointEditorActions";

const pausedFlow = {
  flow_id: "flow-abc123",
  transport: "http",
  provisional_exchange_id: null,
} as PausedFlow;

describe("BreakpointEditor action boundaries", () => {
  it("uses the provisional exchange for detail invalidation when present", () => {
    expect(
      getExchangeDetailQueryKey({
        ...pausedFlow,
        provisional_exchange_id: "exchange-provisional-1",
      }),
    ).toEqual(["exchange", "exchange-provisional-1"]);
  });

  it("waits for stream completion after an HTTP release", () => {
    expect(getReleasedFlowCompletion(pausedFlow)).toEqual({
      shouldWaitForStream: true,
      selectedId: null,
    });
  });

  it("resolves websocket releases immediately and selects the provisional exchange", () => {
    expect(
      getReleasedFlowCompletion({
        ...pausedFlow,
        transport: "websocket",
        provisional_exchange_id: "exchange-provisional-2",
      }),
    ).toEqual({
      shouldWaitForStream: false,
      selectedId: "exchange-provisional-2",
    });
  });
});
