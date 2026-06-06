import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ViewerProps } from "../../model/paneRecords";
import {
  installMockTransport,
  jsonResponse,
  makeSessionSummary,
  renderWithQuery,
  restoreTransport,
} from "../../testUtils";
import { SessionPickerPane } from "./SessionPickerPane";

describe("SessionPickerPane", () => {
  afterEach(() => restoreTransport());

  it("renders sessions and opens the selected row", async () => {
    const session = makeSessionSummary({ title: "Live project" });
    const open = vi.fn();
    installMockTransport(() => jsonResponse([session]));

    renderWithQuery(<SessionPickerPane {...pickerProps({ spawnOrFocusTranscript: open })} />);

    await waitFor(() => expect(screen.getByText("Live project")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Live project/ }));

    expect(open).toHaveBeenCalledWith(session);
  });

  it("shows the pending launch state when no session row exists yet", async () => {
    installMockTransport(() => jsonResponse([]));

    renderWithQuery(
      <SessionPickerPane {...pickerProps({ launchStatus: "pending", launch: { cli: "codex" } })} />,
    );

    await waitFor(() => {
      expect(screen.getByText("Waiting for live codex session")).toBeInTheDocument();
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
    });
  });

  it("shows an inline retry on error", async () => {
    installMockTransport(() => jsonResponse({}, 500));

    renderWithQuery(<SessionPickerPane {...pickerProps()} />);

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Session lookup failed"),
    );
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});

function pickerProps(
  patch: {
    launch?: { cli?: string | null };
    launchStatus?: "pending" | "resolved" | "unavailable";
    spawnOrFocusTranscript?: ViewerProps["actions"]["spawnOrFocusTranscript"];
  } = {},
): ViewerProps<{ kind: "session-picker"; owner: "local" }> {
  return {
    pane: {
      paneId: "session-picker",
      viewerId: "session-picker",
      title: "Session picker",
      contentRef: { kind: "session-picker", owner: "local" },
      chromeState: "default",
      createdAt: "2026-06-06T17:00:00Z",
      lastFocusedAt: null,
    },
    canvas: {
      id: "hash-1",
      owner: "local",
      workspaceHash: "hash-1",
      focusedPaneId: "session-picker",
      launch: {
        owner: "local",
        workspaceHash: "hash-1",
        cli: patch.launch?.cli ?? "claude",
        runId: null,
      },
      launchStatus: patch.launchStatus ?? "unavailable",
      launchSessionId: null,
    },
    actions: {
      closePane: vi.fn(),
      focusPane: vi.fn(),
      spawnOrFocusTranscript: patch.spawnOrFocusTranscript ?? vi.fn(),
    },
  };
}
