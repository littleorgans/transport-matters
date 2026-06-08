import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ViewerProps } from "../../model/paneRecords";
import {
  installMockTransport,
  jsonResponse,
  makeSessionEvent,
  renderWithQuery,
  restoreTransport,
} from "../../testUtils";
import { TranscriptChatPane } from "./TranscriptChatPane";

class MockEventSource {
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  close = vi.fn();
}

describe("TranscriptChatPane", () => {
  beforeEach(() => {
    vi.stubGlobal("EventSource", MockEventSource);
  });

  afterEach(() => {
    restoreTransport();
    vi.unstubAllGlobals();
  });

  it("renders backlog events", async () => {
    installMockTransport(() => jsonResponse({ events: [makeSessionEvent()], next_from_seq: null }));

    renderWithQuery(<TranscriptChatPane {...transcriptProps()} />);

    await waitFor(() => expect(screen.getByText("hello transcript")).toBeInTheDocument());
  });

  it("shows an inline retry on backlog errors", async () => {
    installMockTransport(() => jsonResponse({}, 500));

    renderWithQuery(<TranscriptChatPane {...transcriptProps()} />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Transcript failed"));
  });
});

function transcriptProps(): ViewerProps<{
  kind: "session-timeline";
  owner: "local";
  sessionId: string;
}> {
  return {
    pane: {
      paneId: "transcript:session-1",
      viewerId: "transcript-chat",
      title: "Transcript",
      contentRef: { kind: "session-timeline", owner: "local", sessionId: "session-1" },
      chromeState: "default",
      createdAt: "2026-06-06T17:00:00Z",
      lastFocusedAt: null,
    },
    canvas: {
      id: "hash-1",
      owner: "local",
      workspaceHash: "hash-1",
      focusedPaneId: "transcript:session-1",
      launch: { owner: "local", workspaceHash: "hash-1", cli: "claude", runId: null },
      launchStatus: "unavailable",
      launchSessionId: null,
    },
    actions: {
      closePane: vi.fn(),
      focusPane: vi.fn(),
      spawnOrFocusTranscript: vi.fn(),
    },
  };
}
