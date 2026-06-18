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
    installMockTransport(() => jsonResponse({ events: [makeSessionEvent()], nextFromSeq: null }));

    renderWithQuery(<TranscriptChatPane {...transcriptProps()} />);

    await waitFor(() => expect(screen.getByText("hello transcript")).toBeInTheDocument());
  });

  it("renders wire injected turns with their label and affordance", async () => {
    installMockTransport(() =>
      jsonResponse({
        events: [
          makeSessionEvent({
            role: "system",
            body: {
              kind: "wire_injected",
              label: "System reminder",
              parts: [{ type: "text", text: "remember the policy" }],
            },
            nativePayload: {
              type: "attachment",
              attachment: {
                type: "hook_success",
                stdout: "remember the policy",
              },
            },
          }),
        ],
        nextFromSeq: null,
      }),
    );

    renderWithQuery(<TranscriptChatPane {...transcriptProps()} />);

    await waitFor(() => {
      const message = screen.getByText("remember the policy").closest("article");
      expect(message).toHaveAttribute("data-kind", "wire_context");
      expect(message).toHaveAttribute("data-role", "wire");
      expect(screen.getByText("System reminder")).toBeInTheDocument();
      expect(screen.getByText("view raw")).toBeInTheDocument();
    });
  });

  it("hides raw details and renders metadata fallback for null native payloads", async () => {
    installMockTransport(() =>
      jsonResponse({
        events: [
          makeSessionEvent({
            kind: "meta",
            role: null,
            seq: 7,
            turnIndex: 3,
            ts: "2026-06-06T18:00:00Z",
            body: { kind: "wire_injected", label: "meta", parts: [] },
            nativePayload: null,
          }),
        ],
        nextFromSeq: null,
      }),
    );

    renderWithQuery(<TranscriptChatPane {...transcriptProps()} />);

    await waitFor(() => {
      expect(screen.getByText(/kind: meta/)).toBeInTheDocument();
      expect(screen.getByText(/body: wire_injected/)).toBeInTheDocument();
      expect(screen.queryByText("view raw")).not.toBeInTheDocument();
    });
  });

  it("renders tool use and tool result bodies", async () => {
    installMockTransport(() =>
      jsonResponse({
        events: [
          makeSessionEvent({
            seq: 1,
            body: { kind: "tool_use", toolName: "Read", input: { file: "a.ts" } },
          }),
          makeSessionEvent({
            seq: 2,
            body: { kind: "tool_result", toolName: "Read", output: "contents", isError: false },
          }),
        ],
        nextFromSeq: null,
      }),
    );

    renderWithQuery(<TranscriptChatPane {...transcriptProps()} />);

    await waitFor(() => {
      expect(screen.getByText(/tool_use: Read/)).toBeInTheDocument();
      expect(screen.getByText(/tool_result: Read/)).toBeInTheDocument();
      expect(screen.getByText(/contents/)).toBeInTheDocument();
    });
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
      launch: { owner: "local", workspaceHash: "hash-1", harness: "claude", runId: null },
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
