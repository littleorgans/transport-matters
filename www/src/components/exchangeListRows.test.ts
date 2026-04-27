import { describe, expect, it, vi } from "vitest";
import { buildExchangeTrackTree } from "../hooks/useExchanges";
import type { ExchangeTrack, ExchangeTrackStub, IndexEntry, SpawnAnchor } from "../types";
import { makeEntry } from "./__test-utils__/exchangeList";
import { type ExchangeListRow, projectAnchoredRows } from "./exchangeListRows";

const NO_COLLAPSED = new Set<string>();

type RowScenarioEntries = {
  entries: IndexEntry[];
  stubs?: ExchangeTrackStub[];
};

type RowScenario = readonly [
  label: string,
  entries: RowScenarioEntries,
  expectedRowKeys: readonly string[],
];

function rowKeys(rows: ExchangeListRow[]): string[] {
  return rows.map((row) => row.key);
}

function exchangeIdAt(rows: ExchangeListRow[], index: number): string | null {
  const row = rows[index];
  return row && row.type === "exchange" ? row.entry.id : null;
}

function trackIdAt(rows: ExchangeListRow[], index: number): string | null {
  const row = rows[index];
  return row && row.type === "track" ? row.track.track_id : null;
}

function trackRow(
  rows: ExchangeListRow[],
  trackId: string,
): Extract<ExchangeListRow, { type: "track" }> {
  const row = rows.find(
    (candidate) => candidate.type === "track" && candidate.track.track_id === trackId,
  );
  expect(row?.type).toBe("track");
  return row as Extract<ExchangeListRow, { type: "track" }>;
}

function anchor(exchangeId: string, toolUseId: string | null = null, order = 0): SpawnAnchor {
  return {
    track_spawn_exchange_id: exchangeId,
    track_spawn_tool_use_id: toolUseId,
    track_spawn_order: order,
  };
}

function parentEntry(id: string, ts?: string): IndexEntry {
  return makeEntry({
    id,
    run_id: "run-1",
    track_id: "run-1",
    track_role: "parent",
    ...(ts ? { ts } : {}),
  });
}

function childEntry(
  id: string,
  trackId: string,
  parentTrackId: string,
  spawnAnchor: SpawnAnchor,
  ts?: string,
): IndexEntry {
  return makeEntry({
    id,
    run_id: "run-1",
    track_id: trackId,
    parent_track_id: parentTrackId,
    track_role: "subagent",
    spawn_anchor: spawnAnchor,
    ...(ts ? { ts } : {}),
  });
}

function claudeParentEntry(id: string, ts: string): IndexEntry {
  return makeEntry({
    id,
    run_id: "run-claude",
    track_id: "run-claude",
    track_role: "parent",
    provider: "anthropic",
    ts,
  });
}

function claudeChildEntry(id: string, ts: string): IndexEntry {
  return makeEntry({
    id,
    run_id: "run-claude",
    track_id: "toolu_claude_research",
    parent_track_id: "run-claude",
    track_role: "subagent",
    track_display_name: "research",
    provider: "anthropic",
    spawn_anchor: anchor("claude-parent-spawn", "toolu_claude_research"),
    ts,
  });
}

function codexParentEntry(id: string, ts: string): IndexEntry {
  return makeEntry({
    id,
    run_id: "run-codex",
    track_id: "run-codex",
    track_role: "parent",
    provider: "codex",
    model: "gpt-5-codex",
    ts,
  });
}

function codexChildEntry(id: string, ts: string): IndexEntry {
  return makeEntry({
    id,
    run_id: "run-codex",
    track_id: "agent-codex-runner",
    parent_track_id: "run-codex",
    track_role: "subagent",
    track_display_name: "runner",
    provider: "codex",
    model: "gpt-5-codex",
    spawn_anchor: anchor("codex-parent-spawn", "spawn_codex_runner"),
    ts,
  });
}

function anchoredTrackRows(input: RowScenarioEntries): ExchangeListRow[] {
  return projectAnchoredRows(buildExchangeTrackTree(input.entries, input.stubs), NO_COLLAPSED);
}

const rowScenarios: RowScenario[] = [
  [
    "places a Claude subagent track between the spawning and continuation parent exchanges",
    {
      entries: [
        claudeParentEntry("claude-parent-pre", "2026-04-26T00:00:00.000Z"),
        claudeParentEntry("claude-parent-spawn", "2026-04-26T00:01:00.000Z"),
        claudeChildEntry("claude-child-1", "2026-04-26T00:01:30.000Z"),
        claudeChildEntry("claude-child-2", "2026-04-26T00:01:45.000Z"),
        claudeParentEntry("claude-parent-post", "2026-04-26T00:02:00.000Z"),
      ],
    },
    [
      "exchange:claude-parent-post",
      "track:toolu_claude_research",
      "exchange:claude-child-2",
      "exchange:claude-child-1",
      "exchange:claude-parent-spawn",
      "exchange:claude-parent-pre",
    ],
  ],
  [
    "places a Codex subagent track between the spawning and continuation parent exchanges",
    {
      entries: [
        codexParentEntry("codex-parent-pre", "2026-04-26T00:00:00.000Z"),
        codexParentEntry("codex-parent-spawn", "2026-04-26T00:01:00.000Z"),
        codexChildEntry("codex-child-1", "2026-04-26T00:01:30.000Z"),
        codexParentEntry("codex-parent-post", "2026-04-26T00:02:00.000Z"),
      ],
    },
    [
      "exchange:codex-parent-post",
      "track:agent-codex-runner",
      "exchange:codex-child-1",
      "exchange:codex-parent-spawn",
      "exchange:codex-parent-pre",
    ],
  ],
  [
    "anchors child tracks to separate parent exchanges in one parent track",
    {
      entries: [
        parentEntry("p0", "2026-04-26T00:00:00.000Z"),
        parentEntry("p1", "2026-04-26T00:01:00.000Z"),
        parentEntry("p2", "2026-04-26T00:03:00.000Z"),
        childEntry("child-at-p0", "agent-at-p0", "run-1", anchor("p0"), "2026-04-26T00:00:30.000Z"),
        childEntry("child-at-p1", "agent-at-p1", "run-1", anchor("p1"), "2026-04-26T00:02:00.000Z"),
      ],
    },
    [
      "exchange:p2",
      "track:agent-at-p1",
      "exchange:child-at-p1",
      "exchange:p1",
      "track:agent-at-p0",
      "exchange:child-at-p0",
      "exchange:p0",
    ],
  ],
  [
    "renders a one level child track at its parent exchange anchor",
    {
      entries: [parentEntry("p0"), childEntry("child-1", "agent-child", "run-1", anchor("p0"))],
    },
    ["track:agent-child", "exchange:child-1", "exchange:p0"],
  ],
  [
    "renders a two level child track under the exchange that spawned it",
    {
      entries: [
        parentEntry("p0"),
        childEntry("child-1", "agent-child", "run-1", anchor("p0")),
        childEntry("child-2", "agent-child", "run-1", anchor("p0"), "2026-04-26T00:01:00.000Z"),
        childEntry("grand-1", "agent-grand", "agent-child", anchor("child-1")),
      ],
    },
    [
      "track:agent-child",
      "exchange:child-2",
      "track:agent-grand",
      "exchange:grand-1",
      "exchange:child-1",
      "exchange:p0",
    ],
  ],
  [
    "renders pending child tracks at their spawn anchor before any child exchange arrives",
    {
      entries: [parentEntry("p0"), parentEntry("p1", "2026-04-26T00:01:00.000Z")],
      stubs: [
        {
          track_id: "agent-pending",
          parent_track_id: "run-1",
          track_role: "subagent",
          status: "pending",
          spawn_anchor: anchor("p0", "toolu_pending"),
        },
      ],
    },
    ["exchange:p1", "track:agent-pending", "exchange:p0"],
  ],
];

describe("projectAnchoredRows row order matrix", () => {
  it.each(rowScenarios)("%s", (_label, input, expectedRowKeys) => {
    expect(rowKeys(anchoredTrackRows(input))).toEqual(expectedRowKeys);
  });
});

describe("projectAnchoredRows sibling ordering", () => {
  it("orders fan-out sibling tracks at the same anchor by track_spawn_order then track_id", () => {
    const tree = buildExchangeTrackTree([
      parentEntry("p0"),
      childEntry("child-b", "toolu_child_b", "run-1", anchor("p0", "toolu_child_b", 1)),
      childEntry("child-a", "toolu_child_a", "run-1", anchor("p0", "toolu_child_a", 0)),
    ]);

    const rows = projectAnchoredRows(tree, NO_COLLAPSED);
    expect(rowKeys(rows)).toEqual([
      "track:toolu_child_b",
      "exchange:child-b",
      "track:toolu_child_a",
      "exchange:child-a",
      "exchange:p0",
    ]);
  });

  it("breaks ties by track_id when track_spawn_order matches", () => {
    const tree = buildExchangeTrackTree([
      parentEntry("p0"),
      childEntry("child-zebra", "agent-zebra", "run-1", anchor("p0")),
      childEntry("child-alpha", "agent-alpha", "run-1", anchor("p0")),
    ]);

    const rows = projectAnchoredRows(tree, NO_COLLAPSED);
    expect(trackIdAt(rows, 0)).toBe("agent-alpha");
    expect(trackIdAt(rows, 2)).toBe("agent-zebra");
  });
});

describe("projectAnchoredRows edge behavior", () => {
  it("collapsing an anchored child hides its exchanges and descendant tracks", () => {
    const tree = buildExchangeTrackTree([
      parentEntry("p0"),
      childEntry("child-1", "agent-child", "run-1", anchor("p0")),
      childEntry("grand-1", "agent-grand", "agent-child", anchor("child-1")),
    ]);

    const rows = projectAnchoredRows(tree, new Set(["agent-child"]));
    expect(rowKeys(rows)).toEqual(["track:agent-child", "exchange:p0"]);
  });

  it("falls back to end-of-parent placement when an anchor is outside the fetched window", () => {
    const tree = buildExchangeTrackTree([
      parentEntry("p0"),
      childEntry("child-orphan", "agent-orphan", "run-1", anchor("exchange-not-in-window")),
    ]);

    const rows = projectAnchoredRows(tree, NO_COLLAPSED);
    expect(rowKeys(rows)).toEqual(["exchange:p0", "track:agent-orphan", "exchange:child-orphan"]);
    expect(trackRow(rows, "agent-orphan").meta).toEqual({
      orphanAnchor: true,
      missingAnchorId: "exchange-not-in-window",
    });
  });

  it("warns in dev when an anchored child falls outside the fetched window", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const tree = buildExchangeTrackTree([
      parentEntry("p0"),
      childEntry("child-orphan", "agent-orphan", "run-1", anchor("exchange-not-in-window")),
    ]);

    projectAnchoredRows(tree, NO_COLLAPSED);

    expect(warn).toHaveBeenCalledTimes(1);
    expect(warn).toHaveBeenCalledWith(
      expect.stringContaining("outside fetched exchange window"),
      expect.objectContaining({
        trackId: "agent-orphan",
        missingAnchorId: "exchange-not-in-window",
        parentTrackId: "run-1",
      }),
    );
    warn.mockRestore();
  });

  it("falls back to end-of-parent placement without diagnostics when a track has no anchor at all", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const tree = buildExchangeTrackTree([
      parentEntry("p0"),
      makeEntry({
        id: "child-legacy",
        run_id: "run-1",
        track_id: "agent-legacy",
        parent_track_id: "run-1",
        track_role: "subagent",
      }),
    ]);

    const rows = projectAnchoredRows(tree, NO_COLLAPSED);
    expect(rowKeys(rows)).toEqual(["exchange:p0", "track:agent-legacy", "exchange:child-legacy"]);
    expect(trackRow(rows, "agent-legacy").meta).toBeUndefined();
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });

  it("keeps parent exchanges chronological regardless of fetched array order", () => {
    const tree = buildExchangeTrackTree([
      parentEntry("p2", "2026-04-26T00:02:00.000Z"),
      parentEntry("p0", "2026-04-26T00:00:00.000Z"),
      parentEntry("p1", "2026-04-26T00:01:00.000Z"),
    ]);

    const rows = projectAnchoredRows(tree, NO_COLLAPSED);
    expect(exchangeIdAt(rows, 0)).toBe("p2");
    expect(exchangeIdAt(rows, 1)).toBe("p1");
    expect(exchangeIdAt(rows, 2)).toBe("p0");
  });

  it("numbers turnSequence per track, independent of where anchored children land", () => {
    const tree = buildExchangeTrackTree([
      parentEntry("p0", "2026-04-26T00:00:00.000Z"),
      parentEntry("p1", "2026-04-26T00:01:00.000Z"),
      parentEntry("p2", "2026-04-26T00:02:00.000Z"),
      childEntry("child-1", "agent-child", "run-1", anchor("p0"), "2026-04-26T00:00:30.000Z"),
      childEntry("child-2", "agent-child", "run-1", anchor("p0"), "2026-04-26T00:00:45.000Z"),
    ]);

    const rows = projectAnchoredRows(tree, NO_COLLAPSED);
    const turns = rows.flatMap((row) =>
      row.type === "exchange" ? [{ id: row.entry.id, turn: row.turnSequence }] : [],
    );
    const byId = new Map(turns.map((t) => [t.id, t.turn]));
    expect(byId.get("p0")).toBe(1);
    expect(byId.get("p1")).toBe(2);
    expect(byId.get("p2")).toBe(3);
    expect(byId.get("child-1")).toBe(1);
    expect(byId.get("child-2")).toBe(2);
  });

  it("keeps nested depth tied to the spawning track level", () => {
    const rows = anchoredTrackRows({
      entries: [
        parentEntry("p0"),
        childEntry("child-1", "agent-child", "run-1", anchor("p0")),
        childEntry("grand-1", "agent-grand", "agent-child", anchor("child-1")),
      ],
    });

    expect(trackRow(rows, "agent-child").depth).toBe(1);
    expect(trackRow(rows, "agent-grand").depth).toBe(2);
    expect(rows.find((row) => row.key === "exchange:child-1")?.depth).toBe(2);
    expect(rows.find((row) => row.key === "exchange:grand-1")?.depth).toBe(3);
  });

  it("returns stable row keys for virtualization", () => {
    const tracks: ExchangeTrack[] = buildExchangeTrackTree([
      parentEntry("p0"),
      childEntry("child-1", "agent-child", "run-1", anchor("p0")),
    ]);

    const a = projectAnchoredRows(tracks, NO_COLLAPSED);
    const b = projectAnchoredRows(tracks, NO_COLLAPSED);
    expect(rowKeys(a)).toEqual(rowKeys(b));
    expect(a[0]?.key).toBe("track:agent-child");
    expect(a[1]?.key).toBe("exchange:child-1");
  });
});
