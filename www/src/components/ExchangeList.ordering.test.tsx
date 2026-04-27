import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { makeEntry } from "./__test-utils__/exchangeList";
import { ExchangeList } from "./ExchangeList";

function rowTestIds(): string[] {
  return Array.from(
    document.querySelectorAll<HTMLElement>(
      '[data-testid^="exchange-row-"], [data-testid^="track-header-"]',
    ),
    (element) => element.getAttribute("data-testid") ?? "",
  );
}

describe("ExchangeList — anchored ordering", () => {
  it("renders a Claude anchored subagent track with selected row state", () => {
    render(
      <ExchangeList
        exchanges={[
          makeEntry({
            id: "claude-parent-pre",
            run_id: "run-claude",
            track_id: "run-claude",
            track_role: "parent",
            ts: "2026-04-26T00:00:00.000Z",
          }),
          makeEntry({
            id: "claude-parent-spawn",
            run_id: "run-claude",
            track_id: "run-claude",
            track_role: "parent",
            ts: "2026-04-26T00:01:00.000Z",
          }),
          makeEntry({
            id: "claude-child-1",
            run_id: "run-claude",
            track_id: "toolu_claude_research",
            parent_track_id: "run-claude",
            track_role: "subagent",
            track_display_name: "research",
            spawn_anchor: {
              track_spawn_exchange_id: "claude-parent-spawn",
              track_spawn_tool_use_id: "toolu_claude_research",
              track_spawn_order: 0,
            },
            ts: "2026-04-26T00:01:30.000Z",
          }),
          makeEntry({
            id: "claude-parent-post",
            run_id: "run-claude",
            track_id: "run-claude",
            track_role: "parent",
            ts: "2026-04-26T00:02:00.000Z",
          }),
        ]}
        currentRunId="run-claude"
        includeHistory={false}
        onIncludeHistoryChange={() => {}}
        selectedId="claude-child-1"
        onSelect={() => {}}
      />,
    );

    expect(screen.getByText("research")).toBeInTheDocument();
    expect(rowTestIds()).toEqual([
      "exchange-row-claude-parent-post",
      "track-header-toolu_claude_research",
      "exchange-row-claude-child-1",
      "exchange-row-claude-parent-spawn",
      "exchange-row-claude-parent-pre",
    ]);
    expect(
      screen.getByTestId("exchange-row-claude-child-1").querySelector(".row-selected"),
    ).toBeTruthy();
  });

  it("renders a Codex anchored subagent track with row selection wiring", () => {
    const onSelect = vi.fn();
    render(
      <ExchangeList
        exchanges={[
          makeEntry({
            id: "codex-parent-pre",
            run_id: "run-codex",
            track_id: "run-codex",
            track_role: "parent",
            provider: "codex",
            model: "codex/gpt-5-codex",
            ts: "2026-04-26T00:00:00.000Z",
          }),
          makeEntry({
            id: "codex-parent-spawn",
            run_id: "run-codex",
            track_id: "run-codex",
            track_role: "parent",
            provider: "codex",
            model: "codex/gpt-5-codex",
            ts: "2026-04-26T00:01:00.000Z",
          }),
          makeEntry({
            id: "codex-child-1",
            run_id: "run-codex",
            track_id: "agent-codex-runner",
            parent_track_id: "run-codex",
            track_role: "subagent",
            track_display_name: "runner",
            provider: "codex",
            model: "codex/gpt-5-codex",
            spawn_anchor: {
              track_spawn_exchange_id: "codex-parent-spawn",
              track_spawn_tool_use_id: "spawn_codex_runner",
              track_spawn_order: 0,
            },
            ts: "2026-04-26T00:01:30.000Z",
          }),
          makeEntry({
            id: "codex-parent-post",
            run_id: "run-codex",
            track_id: "run-codex",
            track_role: "parent",
            provider: "codex",
            model: "codex/gpt-5-codex",
            ts: "2026-04-26T00:02:00.000Z",
          }),
        ]}
        currentRunId="run-codex"
        includeHistory={false}
        onIncludeHistoryChange={() => {}}
        selectedId={null}
        onSelect={onSelect}
      />,
    );

    expect(screen.getByText("runner")).toBeInTheDocument();
    expect(screen.getAllByText("gpt-5-codex")).not.toHaveLength(0);
    expect(rowTestIds()).toEqual([
      "exchange-row-codex-parent-post",
      "track-header-agent-codex-runner",
      "exchange-row-codex-child-1",
      "exchange-row-codex-parent-spawn",
      "exchange-row-codex-parent-pre",
    ]);

    fireEvent.click(screen.getByTestId("exchange-row-codex-child-1"));
    expect(onSelect).toHaveBeenCalledWith("codex-child-1");
  });

  it("nests a grandchild track under the subagent exchange that spawned it", () => {
    render(
      <ExchangeList
        exchanges={[
          makeEntry({
            id: "p0",
            run_id: "run-1",
            track_id: "run-1",
            track_role: "parent",
            ts: "2026-04-26T00:00:00.000Z",
          }),
          makeEntry({
            id: "child-1",
            run_id: "run-1",
            track_id: "agent-child",
            parent_track_id: "run-1",
            track_role: "subagent",
            track_display_name: "child",
            spawn_anchor: {
              track_spawn_exchange_id: "p0",
              track_spawn_tool_use_id: "toolu_child",
              track_spawn_order: 0,
            },
            ts: "2026-04-26T00:00:30.000Z",
          }),
          makeEntry({
            id: "grand-1",
            run_id: "run-1",
            track_id: "agent-grand",
            parent_track_id: "agent-child",
            track_role: "subagent",
            track_display_name: "grand",
            spawn_anchor: {
              track_spawn_exchange_id: "child-1",
              track_spawn_tool_use_id: "toolu_grand",
              track_spawn_order: 0,
            },
            ts: "2026-04-26T00:00:45.000Z",
          }),
        ]}
        currentRunId="run-1"
        includeHistory={false}
        onIncludeHistoryChange={() => {}}
        selectedId={null}
        onSelect={() => {}}
      />,
    );

    expect(screen.getByText("child")).toBeInTheDocument();
    expect(screen.getByText("grand")).toBeInTheDocument();
    expect(rowTestIds()).toEqual([
      "track-header-agent-child",
      "track-header-agent-grand",
      "exchange-row-grand-1",
      "exchange-row-child-1",
      "exchange-row-p0",
    ]);
    expect(screen.getByTestId("track-header-agent-grand")).toHaveAttribute("data-depth", "2");
  });

  it("renders a child whose anchor is outside the fetched window", () => {
    render(
      <ExchangeList
        exchanges={[
          makeEntry({
            id: "p0",
            run_id: "run-1",
            track_id: "run-1",
            track_role: "parent",
            ts: "2026-04-26T00:00:00.000Z",
          }),
          makeEntry({
            id: "p1",
            run_id: "run-1",
            track_id: "run-1",
            track_role: "parent",
            ts: "2026-04-26T00:01:00.000Z",
          }),
          makeEntry({
            id: "child-orphan-1",
            run_id: "run-1",
            track_id: "agent-orphan",
            parent_track_id: "run-1",
            track_role: "subagent",
            track_display_name: "orphan",
            spawn_anchor: {
              track_spawn_exchange_id: "exchange-not-fetched",
              track_spawn_tool_use_id: null,
              track_spawn_order: 0,
            },
            ts: "2026-04-26T00:00:30.000Z",
          }),
        ]}
        currentRunId="run-1"
        includeHistory={false}
        onIncludeHistoryChange={() => {}}
        selectedId={null}
        onSelect={() => {}}
      />,
    );

    expect(screen.getByText("orphan")).toBeInTheDocument();
    expect(screen.getByTestId("track-header-agent-orphan")).toHaveTextContent(
      "anchor outside view",
    );
    expect(screen.getByTestId("exchange-row-child-orphan-1")).toBeInTheDocument();
    expect(rowTestIds()).toEqual([
      "exchange-row-p1",
      "exchange-row-p0",
      "track-header-agent-orphan",
      "exchange-row-child-orphan-1",
    ]);
  });

  it("collapsing an anchored child hides its exchanges and descendant tracks", () => {
    render(
      <ExchangeList
        exchanges={[
          makeEntry({
            id: "p0",
            run_id: "run-1",
            track_id: "run-1",
            track_role: "parent",
            ts: "2026-04-26T00:00:00.000Z",
          }),
          makeEntry({
            id: "child-1",
            run_id: "run-1",
            track_id: "agent-child",
            parent_track_id: "run-1",
            track_role: "subagent",
            track_display_name: "child",
            spawn_anchor: {
              track_spawn_exchange_id: "p0",
              track_spawn_tool_use_id: null,
              track_spawn_order: 0,
            },
            ts: "2026-04-26T00:00:30.000Z",
          }),
          makeEntry({
            id: "grand-1",
            run_id: "run-1",
            track_id: "agent-grand",
            parent_track_id: "agent-child",
            track_role: "subagent",
            track_display_name: "grand",
            spawn_anchor: {
              track_spawn_exchange_id: "child-1",
              track_spawn_tool_use_id: null,
              track_spawn_order: 0,
            },
            ts: "2026-04-26T00:00:45.000Z",
          }),
        ]}
        currentRunId="run-1"
        includeHistory={false}
        onIncludeHistoryChange={() => {}}
        selectedId={null}
        onSelect={() => {}}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Collapse track agent-child" }));

    expect(screen.queryByTestId("exchange-row-child-1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("exchange-row-grand-1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("track-header-agent-grand")).not.toBeInTheDocument();
    expect(screen.getByTestId("track-header-agent-child")).toBeInTheDocument();
  });

  it("focuses the spawning parent exchange when a child track header is clicked", () => {
    const onSelect = vi.fn();
    render(
      <ExchangeList
        exchanges={[
          makeEntry({
            id: "parent-pre",
            run_id: "run-1",
            track_id: "run-1",
            track_role: "parent",
            ts: "2026-04-26T00:00:00.000Z",
          }),
          makeEntry({
            id: "parent-spawn",
            run_id: "run-1",
            track_id: "run-1",
            track_role: "parent",
            ts: "2026-04-26T00:01:00.000Z",
          }),
          makeEntry({
            id: "child-1",
            run_id: "run-1",
            track_id: "agent-child",
            parent_track_id: "run-1",
            track_role: "subagent",
            track_display_name: "research",
            spawn_anchor: {
              track_spawn_exchange_id: "parent-spawn",
              track_spawn_tool_use_id: null,
              track_spawn_order: 0,
            },
            ts: "2026-04-26T00:01:30.000Z",
          }),
          makeEntry({
            id: "parent-post",
            run_id: "run-1",
            track_id: "run-1",
            track_role: "parent",
            ts: "2026-04-26T00:02:00.000Z",
          }),
        ]}
        currentRunId="run-1"
        includeHistory={false}
        onIncludeHistoryChange={() => {}}
        selectedId={null}
        onSelect={onSelect}
      />,
    );

    fireEvent.click(screen.getByText("research"));
    expect(onSelect).toHaveBeenCalledWith("parent-spawn");
  });

  it("focuses the latest parent exchange at or before the child's first exchange when no spawn anchor is set", () => {
    const onSelect = vi.fn();
    render(
      <ExchangeList
        exchanges={[
          makeEntry({
            id: "legacy-parent-pre",
            run_id: "run-1",
            track_id: "run-1",
            track_role: "parent",
            ts: "2026-04-26T00:00:00.000Z",
          }),
          makeEntry({
            id: "legacy-parent-spawn",
            run_id: "run-1",
            track_id: "run-1",
            track_role: "parent",
            ts: "2026-04-26T00:01:00.000Z",
          }),
          makeEntry({
            id: "legacy-child-1",
            run_id: "run-1",
            track_id: "agent-legacy",
            parent_track_id: "run-1",
            track_role: "subagent",
            track_display_name: "legacy",
            ts: "2026-04-26T00:01:30.000Z",
          }),
          makeEntry({
            id: "legacy-parent-post",
            run_id: "run-1",
            track_id: "run-1",
            track_role: "parent",
            ts: "2026-04-26T00:02:00.000Z",
          }),
        ]}
        currentRunId="run-1"
        includeHistory={false}
        onIncludeHistoryChange={() => {}}
        selectedId={null}
        onSelect={onSelect}
      />,
    );

    fireEvent.click(screen.getByText("legacy"));
    expect(onSelect).toHaveBeenCalledWith("legacy-parent-spawn");
  });
});
