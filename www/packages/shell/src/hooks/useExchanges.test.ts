import type { ExchangeTrackStub, IndexEntry, SpawnAnchor } from "@tm/core/types/exchanges";
import { describe, expect, it } from "vitest";
import { makeEntry } from "../components/__test-utils__/exchangeList";
import { buildExchangeTrackTree } from "./useExchanges";

function spawnAnchor(exchangeId: string, toolUseId: string, order: number): SpawnAnchor {
  return {
    track_spawn_exchange_id: exchangeId,
    track_spawn_tool_use_id: toolUseId,
    track_spawn_order: order,
  };
}

describe("buildExchangeTrackTree spawn anchors", () => {
  it("preserves anchor fields from a pending track stub before child exchanges arrive", () => {
    const stubs: ExchangeTrackStub[] = [
      {
        track_id: "toolu_child_a",
        parent_track_id: "run-1",
        track_display_name: "research-a",
        track_role: "subagent",
        status: "pending",
        spawn_anchor: {
          track_spawn_exchange_id: "exchange-parent-1",
          track_spawn_tool_use_id: "toolu_child_a",
          track_spawn_order: 0,
        },
      },
    ];

    const [stubTrack, ...rest] = buildExchangeTrackTree([], stubs);
    expect(rest).toHaveLength(0);
    if (!stubTrack) throw new Error("expected stub track to be present");
    expect(stubTrack.track_id).toBe("toolu_child_a");
    expect(stubTrack.status).toBe("pending");
    expect(stubTrack.track_spawn_exchange_id).toBe("exchange-parent-1");
    expect(stubTrack.track_spawn_tool_use_id).toBe("toolu_child_a");
    expect(stubTrack.track_spawn_order).toBe(0);
  });

  it("propagates anchor fields from fetched exchange rows onto the derived track", () => {
    const exchanges: IndexEntry[] = [
      makeEntry({
        id: "exchange-child",
        run_id: "run-1",
        track_id: "agent-child",
        parent_track_id: "run-1",
        track_role: "subagent",
        spawn_anchor: {
          track_spawn_exchange_id: "exchange-parent-3",
          track_spawn_tool_use_id: "toolu_child_b",
          track_spawn_order: 1,
        },
      }),
    ];

    const [child] = buildExchangeTrackTree(exchanges);
    if (!child) throw new Error("expected child track to be present");
    expect(child.track_id).toBe("agent-child");
    expect(child.track_spawn_exchange_id).toBe("exchange-parent-3");
    expect(child.track_spawn_tool_use_id).toBe("toolu_child_b");
    expect(child.track_spawn_order).toBe(1);
  });

  it("leaves anchor fields null on a parent track and on legacy rows without anchors", () => {
    const exchanges: IndexEntry[] = [
      makeEntry({
        id: "exchange-parent",
        run_id: "run-1",
        track_id: "run-1",
        track_role: "parent",
      }),
    ];

    const [parent] = buildExchangeTrackTree(exchanges);
    if (!parent) throw new Error("expected parent track to be present");
    expect(parent.track_spawn_exchange_id).toBeNull();
    expect(parent.track_spawn_tool_use_id).toBeNull();
    expect(parent.track_spawn_order).toBeNull();
  });

  it("keeps stub anchor when the first exchange that arrives has no anchor", () => {
    const stubs: ExchangeTrackStub[] = [
      {
        track_id: "agent-late",
        parent_track_id: "run-1",
        track_role: "subagent",
        status: "pending",
        spawn_anchor: {
          track_spawn_exchange_id: "exchange-parent-7",
          track_spawn_tool_use_id: "toolu_late",
          track_spawn_order: 0,
        },
      },
    ];
    const exchanges: IndexEntry[] = [
      makeEntry({
        id: "exchange-late",
        run_id: "run-1",
        track_id: "agent-late",
        parent_track_id: "run-1",
        track_role: "subagent",
      }),
    ];

    const [child] = buildExchangeTrackTree(exchanges, stubs);
    if (!child) throw new Error("expected child track to be present");
    expect(child.track_spawn_exchange_id).toBe("exchange-parent-7");
    expect(child.track_spawn_tool_use_id).toBe("toolu_late");
    expect(child.track_spawn_order).toBe(0);
  });

  function expectSingleTrackAnchor(
    exchanges: IndexEntry[],
    stubs: ExchangeTrackStub[],
    expectedAnchor: SpawnAnchor,
  ) {
    const [child] = buildExchangeTrackTree(exchanges, stubs);
    if (!child) throw new Error("expected child track to be present");
    expect(child.track_spawn_exchange_id).toBe(expectedAnchor.track_spawn_exchange_id);
    expect(child.track_spawn_tool_use_id).toBe(expectedAnchor.track_spawn_tool_use_id);
    expect(child.track_spawn_order).toBe(expectedAnchor.track_spawn_order);
  }

  it("keeps p0 when stub anchored to p0 is followed by entry anchored to p0", () => {
    const p0 = spawnAnchor("p0", "toolu_p0", 0);
    const stubs: ExchangeTrackStub[] = [
      {
        track_id: "agent-stable",
        parent_track_id: "run-1",
        track_role: "subagent",
        status: "pending",
        spawn_anchor: p0,
      },
    ];
    const exchanges: IndexEntry[] = [
      makeEntry({
        id: "exchange-stable",
        run_id: "run-1",
        track_id: "agent-stable",
        parent_track_id: "run-1",
        track_role: "subagent",
        spawn_anchor: p0,
      }),
    ];

    expectSingleTrackAnchor(exchanges, stubs, p0);
  });

  it("keeps p0 when entry anchored to p0 is followed by matching stub data", () => {
    const p0 = spawnAnchor("p0", "toolu_p0", 0);
    const exchanges: IndexEntry[] = [
      makeEntry({
        id: "exchange-stable",
        run_id: "run-1",
        track_id: "agent-stable",
        parent_track_id: "run-1",
        track_role: "subagent",
        spawn_anchor: p0,
      }),
    ];
    const stubs: ExchangeTrackStub[] = [
      {
        track_id: "agent-stable",
        parent_track_id: "run-1",
        track_role: "subagent",
        status: "pending",
        spawn_anchor: p0,
      },
    ];

    expectSingleTrackAnchor(exchanges, [], p0);
    expectSingleTrackAnchor(exchanges, stubs, p0);
  });

  it("adopts p1 when stub anchored to p0 is followed by entry anchored to p1", () => {
    const p0 = spawnAnchor("p0", "toolu_p0", 0);
    const p1 = spawnAnchor("p1", "toolu_p1", 1);
    const stubs: ExchangeTrackStub[] = [
      {
        track_id: "agent-stable",
        parent_track_id: "run-1",
        track_role: "subagent",
        status: "pending",
        spawn_anchor: p0,
      },
    ];
    const exchanges: IndexEntry[] = [
      makeEntry({
        id: "exchange-stable",
        run_id: "run-1",
        track_id: "agent-stable",
        parent_track_id: "run-1",
        track_role: "subagent",
        spawn_anchor: p1,
      }),
    ];

    expectSingleTrackAnchor(exchanges, stubs, p1);
  });

  it("keeps p1 when entry anchored to p1 is followed by stale stub data anchored to p0", () => {
    const p0 = spawnAnchor("p0", "toolu_p0", 0);
    const p1 = spawnAnchor("p1", "toolu_p1", 1);
    const exchanges: IndexEntry[] = [
      makeEntry({
        id: "exchange-stable",
        run_id: "run-1",
        track_id: "agent-stable",
        parent_track_id: "run-1",
        track_role: "subagent",
        spawn_anchor: p1,
      }),
    ];
    const stubs: ExchangeTrackStub[] = [
      {
        track_id: "agent-stable",
        parent_track_id: "run-1",
        track_role: "subagent",
        status: "pending",
        spawn_anchor: p0,
      },
    ];

    expectSingleTrackAnchor(exchanges, [], p1);
    expectSingleTrackAnchor(exchanges, stubs, p1);
  });
});
