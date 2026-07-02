import { fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import { makeEntry } from "./__test-utils__/exchangeList";
import { ExchangeListWithTrackTree as ExchangeList } from "./__test-utils__/exchangeListHarness";

describe("ExchangeList — track tree", () => {
  it("treats root tracks as structural containers and renders root exchanges flush", () => {
    render(
      <ExchangeList
        exchanges={[
          makeEntry({
            id: "root-1",
            run_id: "run-1",
            track_id: "run-1",
            track_role: "parent",
          }),
        ]}
        currentRunId="run-1"
        includeHistory={false}
        onIncludeHistoryChange={() => {}}
        selectedId={null}
        onSelect={() => {}}
      />,
    );

    expect(screen.queryByTestId("track-header-run-1")).not.toBeInTheDocument();
    expect(screen.getByText("claude-sonnet-4-20250514")).toBeInTheDocument();
    expect(screen.getByText("claude-sonnet-4-20250514").closest("button")).toHaveAttribute(
      "data-depth",
      "0",
    );
  });

  it("renders a parent track with an indented subagent track", () => {
    render(
      <ExchangeList
        exchanges={[
          makeEntry({
            id: "parent-1",
            run_id: "run-1",
            track_id: "run-1",
            track_role: "parent",
          }),
          makeEntry({
            id: "child-1",
            run_id: "run-1",
            track_id: "toolu_01MiLL7GyXKvFTneZmojAazu",
            parent_track_id: "run-1",
            track_display_name: "helioy-tools:deep-research",
            track_role: "subagent",
            model: "anthropic/claude-opus-4-7",
          }),
        ]}
        currentRunId="run-1"
        includeHistory={false}
        onIncludeHistoryChange={() => {}}
        selectedId={null}
        onSelect={() => {}}
      />,
    );

    expect(screen.queryByTestId("track-header-run-1")).not.toBeInTheDocument();
    expect(screen.getByText("helioy-tools:deep-research")).toBeInTheDocument();
    expect(screen.queryByText("toolu_01MiLL7GyXKvFTneZmojAazu")).not.toBeInTheDocument();
    expect(screen.getByTestId("track-header-toolu_01MiLL7GyXKvFTneZmojAazu")).toHaveAttribute(
      "data-depth",
      "1",
    );
    expect(screen.getByText("claude-opus-4-7")).toBeInTheDocument();
  });

  it("renders fan-out sibling subagent tracks and upgrades both to live when exchanges arrive", () => {
    const { rerender } = render(
      <ExchangeList
        exchanges={[
          makeEntry({
            id: "parent-1",
            run_id: "run-1",
            track_id: "run-1",
            track_role: "parent",
          }),
        ]}
        trackStubs={[
          {
            track_id: "toolu_child_a",
            parent_track_id: "run-1",
            track_display_name: "research-a",
            track_role: "subagent",
          },
          {
            track_id: "toolu_child_b",
            parent_track_id: "run-1",
            track_display_name: "research-b",
            track_role: "subagent",
          },
        ]}
        currentRunId="run-1"
        includeHistory={false}
        onIncludeHistoryChange={() => {}}
        selectedId={null}
        onSelect={() => {}}
      />,
    );

    expect(screen.getByText("research-a")).toBeInTheDocument();
    expect(screen.getByText("research-b")).toBeInTheDocument();
    expect(screen.getAllByText("pending")).toHaveLength(2);

    rerender(
      <ExchangeList
        exchanges={[
          makeEntry({
            id: "parent-1",
            run_id: "run-1",
            track_id: "run-1",
            track_role: "parent",
          }),
          makeEntry({
            id: "child-a-1",
            run_id: "run-1",
            track_id: "toolu_child_a",
            parent_track_id: "run-1",
            track_display_name: "research-a",
            track_role: "subagent",
            model: "anthropic/claude-opus-4-7",
          }),
          makeEntry({
            id: "child-b-1",
            run_id: "run-1",
            track_id: "toolu_child_b",
            parent_track_id: "run-1",
            track_display_name: "research-b",
            track_role: "subagent",
            model: "anthropic/claude-haiku-4-5",
          }),
        ]}
        trackStubs={[
          {
            track_id: "toolu_child_a",
            parent_track_id: "run-1",
            track_display_name: "research-a",
            track_role: "subagent",
          },
          {
            track_id: "toolu_child_b",
            parent_track_id: "run-1",
            track_display_name: "research-b",
            track_role: "subagent",
          },
        ]}
        currentRunId="run-1"
        includeHistory={false}
        onIncludeHistoryChange={() => {}}
        selectedId={null}
        onSelect={() => {}}
      />,
    );

    expect(screen.queryByText("pending")).not.toBeInTheDocument();
    expect(screen.getAllByText("live")).toHaveLength(2);
    expect(screen.getByText("claude-opus-4-7")).toBeInTheDocument();
    expect(screen.getByText("claude-haiku-4-5")).toBeInTheDocument();
  });

  it("renders one level of nested subagent tracks", () => {
    render(
      <ExchangeList
        exchanges={[
          makeEntry({
            id: "parent-1",
            run_id: "run-1",
            track_id: "run-1",
            track_role: "parent",
          }),
          makeEntry({
            id: "child-1",
            run_id: "run-1",
            track_id: "agent-child",
            parent_track_id: "run-1",
            track_display_name: "planner",
            track_role: "subagent",
          }),
          makeEntry({
            id: "grandchild-1",
            run_id: "run-1",
            track_id: "agent-grandchild",
            parent_track_id: "agent-child",
            track_display_name: "verifier",
            track_role: "subagent",
          }),
        ]}
        currentRunId="run-1"
        includeHistory={false}
        onIncludeHistoryChange={() => {}}
        selectedId={null}
        onSelect={() => {}}
      />,
    );

    expect(screen.getByText("planner")).toBeInTheDocument();
    expect(screen.getByText("verifier")).toBeInTheDocument();
    expect(screen.getByTestId("track-header-agent-grandchild")).toHaveAttribute("data-depth", "2");
  });

  it("marks the selected exchange inside a subagent track", () => {
    render(
      <ExchangeList
        exchanges={[
          makeEntry({
            id: "parent-1",
            run_id: "run-1",
            track_id: "run-1",
            track_role: "parent",
          }),
          makeEntry({
            id: "child-1",
            run_id: "run-1",
            track_id: "agent-child",
            parent_track_id: "run-1",
            track_display_name: "planner",
            track_role: "subagent",
          }),
        ]}
        currentRunId="run-1"
        includeHistory={false}
        onIncludeHistoryChange={() => {}}
        selectedId="child-1"
        onSelect={() => {}}
      />,
    );

    expect(screen.getByTestId("exchange-row-child-1").querySelector(".row-selected")).toBeTruthy();
  });

  it("renders collapsed subagent tracks from shell state", () => {
    const onToggleCollapsedTrack = vi.fn();
    const props = {
      exchanges: [
        makeEntry({
          id: "parent-1",
          run_id: "run-1",
          track_id: "run-1",
          track_role: "parent",
        }),
        makeEntry({
          id: "child-1",
          run_id: "run-1",
          track_id: "toolu_child",
          parent_track_id: "run-1",
          track_display_name: "researcher",
          track_role: "subagent",
          model: "anthropic/claude-opus-4-7",
        }),
      ],
      currentRunId: "run-1",
      includeHistory: false,
      onIncludeHistoryChange: () => {},
      selectedId: null,
      onSelect: () => {},
    } satisfies ComponentProps<typeof ExchangeList>;

    render(
      <ExchangeList
        {...props}
        collapsedTrackIds={["toolu_child"]}
        onToggleCollapsedTrack={onToggleCollapsedTrack}
      />,
    );

    expect(screen.getByRole("button", { name: "Expand track toolu_child" })).toBeInTheDocument();
    expect(screen.queryByText("claude-opus-4-7")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Expand track toolu_child" }));
    expect(onToggleCollapsedTrack).toHaveBeenCalledWith("toolu_child");
  });
});
