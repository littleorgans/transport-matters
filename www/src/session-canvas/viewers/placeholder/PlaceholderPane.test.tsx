import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { PaneRecord, ViewerProps } from "../../model/paneRecords";
import { titleForRef } from "../registry";
import { PlaceholderPane, type PlaceholderPaneRef } from "./PlaceholderPane";

function placeholderProps(ref: PlaceholderPaneRef, title: string): ViewerProps<PlaceholderPaneRef> {
  const pane: PaneRecord & { contentRef: PlaceholderPaneRef } = {
    paneId: "pane-1",
    viewerId: "placeholder",
    title,
    contentRef: ref,
    chromeState: "default",
    createdAt: "2026-06-08T00:00:00Z",
    lastFocusedAt: null,
  };
  return {
    pane,
    canvas: {
      id: "hash-1",
      owner: "local",
      workspaceHash: "hash-1",
      focusedPaneId: null,
      launch: { owner: "local", workspaceHash: "hash-1", cli: "claude", runId: null },
      launchStatus: "unavailable",
      launchSessionId: null,
    },
    actions: { closePane: vi.fn(), focusPane: vi.fn(), spawnOrFocusTranscript: vi.fn() },
  };
}

describe("PlaceholderPane", () => {
  it("renders subagent identity and the real child-session title from the new SubagentRef shape", () => {
    const ref: PlaceholderPaneRef = {
      kind: "subagent-timeline",
      owner: "local",
      sessionId: "sess-abc",
      subagentId: "sub-xyz",
      parentSessionId: "parent-123",
      parentSeq: 7,
      title: "Investigate auth regression",
    };

    // Title flows ref -> registry titleForRef -> pane.title -> rendered heading.
    render(<PlaceholderPane {...placeholderProps(ref, titleForRef(ref))} />);

    expect(screen.getByText("Investigate auth regression")).toBeInTheDocument();
    // Not the id-fabricated title the registry used before the ref carried a title.
    expect(screen.queryByText(/^Subagent sub-xyz/)).not.toBeInTheDocument();
    expect(screen.getByText("sub-xyz")).toBeInTheDocument();
    expect(screen.getByText("sess-abc")).toBeInTheDocument();
    expect(screen.getByText("parent-123")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
  });

  it("renders a stable subagent pane when parentSeq is null", () => {
    const ref: PlaceholderPaneRef = {
      kind: "subagent-timeline",
      owner: "local",
      sessionId: "s",
      subagentId: "sub",
      parentSessionId: "p",
      parentSeq: null,
      title: "Child task",
    };

    expect(() =>
      render(<PlaceholderPane {...placeholderProps(ref, titleForRef(ref))} />),
    ).not.toThrow();
    expect(screen.queryByText("null")).not.toBeInTheDocument();
  });

  it("renders resource identity", () => {
    const ref: PlaceholderPaneRef = {
      kind: "resource",
      owner: "local",
      sessionId: "sess-1",
      resourceId: "res-9",
    };

    render(<PlaceholderPane {...placeholderProps(ref, "Resource res-9")} />);

    expect(screen.getByText("res-9")).toBeInTheDocument();
    expect(screen.getByText("sess-1")).toBeInTheDocument();
  });

  it("renders provider-exchange as a shell with no data fetching or legacy route state", () => {
    const ref: PlaceholderPaneRef = {
      kind: "provider-exchange",
      owner: "local",
      sessionId: "sess-2",
      exchangeId: "ex-5",
    };

    // Rendered WITHOUT a QueryClientProvider on purpose: a placeholder that queried
    // exchange detail or coupled to legacy route state would throw here.
    render(<PlaceholderPane {...placeholderProps(ref, "Exchange ex-5")} />);

    expect(screen.getByText("ex-5")).toBeInTheDocument();
    expect(screen.getByText("sess-2")).toBeInTheDocument();
    expect(screen.getByText(/not yet wired/i)).toBeInTheDocument();
  });
});
