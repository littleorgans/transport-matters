import { describe, expect, it } from "vitest";
import {
  mockExchangeDetails as barrelDetails,
  mockExchanges as barrelExchanges,
} from "../tests/visual/fixtures";
import { mockExchangeDetails } from "../tests/visual/fixtures/details";
import { mockAnchoredExchanges, mockExchanges } from "../tests/visual/fixtures/exchanges";
import { mockPausedFlow } from "../tests/visual/fixtures/pausedFlow";
import { setupVisualTest } from "../tests/visual/fixtures/setup";
import { FROZEN_NOW } from "../tests/visual/fixtures/time";

describe("visual fixture barrel", () => {
  it("preserves fixture exports while splitting ownership modules", () => {
    expect(FROZEN_NOW.toISOString()).toBe("2026-04-14T10:00:00.000Z");
    expect(mockPausedFlow.paused_at_ms).toBe(FROZEN_NOW.getTime() - 208_000);
    expect(barrelExchanges).toBe(mockExchanges);
    expect(barrelDetails).toBe(mockExchangeDetails);
    expect(typeof setupVisualTest).toBe("function");
  });

  it("includes an anchored subagent exchange for ExchangeList visual coverage", () => {
    const anchoredChild = mockAnchoredExchanges.find((entry) => entry.track_role === "subagent");
    const anchoredParent = mockAnchoredExchanges.find(
      (entry) => entry.id === anchoredChild?.spawn_anchor?.track_spawn_exchange_id,
    );

    expect(anchoredChild).toBeDefined();
    expect(anchoredChild?.track_id).toBeTruthy();
    expect(anchoredChild?.parent_track_id).toBeTruthy();
    expect(anchoredChild?.track_display_name).toBeTruthy();
    expect(anchoredChild?.spawn_anchor?.track_spawn_exchange_id).toBeTruthy();
    expect(anchoredChild?.spawn_anchor?.track_spawn_tool_use_id).toBeTruthy();
    expect(anchoredChild?.spawn_anchor?.track_spawn_order).toBe(0);
    expect(
      mockAnchoredExchanges.some(
        (entry) =>
          entry.id === anchoredChild?.spawn_anchor?.track_spawn_exchange_id &&
          entry.track_id === anchoredChild?.parent_track_id,
      ),
    ).toBe(true);
    expect(anchoredParent?.track_role).toBe("parent");
  });
});
