import { render, screen } from "@testing-library/react";
import type { TransportHttpArtifacts } from "@tm/core/types/transport";
import { describe, expect, it } from "vitest";
import { CodexTransportPanel } from "./CodexTransportPanel";

function httpTransport(overrides: Partial<TransportHttpArtifacts> = {}): TransportHttpArtifacts {
  return {
    provider: "codex",
    protocol: "http",
    request: {
      method: "POST",
      scheme: "https",
      host: "chatgpt.com",
      path: "/backend-api/codex/responses",
      headers: [
        { name: "session-id", value: "sess-http-1" },
        { name: "thread-id", value: "thread-http-1" },
        { name: "x-codex-turn-metadata", value: '{"turn_id":"turn-http-1"}' },
      ],
    },
    response: {
      status_code: 200,
      headers: [{ name: "content-type", value: "text/event-stream" }],
    },
    messages: [
      {
        ts: new Date("2026-01-01T12:00:00Z").toISOString(),
        direction: "client",
        is_text: true,
        size_bytes: 96,
        dropped: false,
        event_type: "response.create",
        payload_text: null,
        payload_json: { type: "response.create", model: "gpt-5-codex" },
        payload_base64: null,
      },
      {
        ts: new Date("2026-01-01T12:00:01Z").toISOString(),
        direction: "server",
        is_text: true,
        size_bytes: 91,
        dropped: false,
        event_type: "response.output_text.delta",
        payload_text: null,
        payload_json: {
          type: "response.output_text.delta",
          delta: "Transport capture completed successfully.",
        },
        payload_base64: null,
      },
    ],
    ...overrides,
  };
}

describe("CodexTransportPanel", () => {
  it("renders HTTP provenance and SSE messages without websocket copy", () => {
    render(<CodexTransportPanel transport={httpTransport()} focusedMessageIndex={null} />);

    expect(screen.getByText("http")).toBeInTheDocument();
    expect(
      screen.getByText("POST https://chatgpt.com/backend-api/codex/responses"),
    ).toBeInTheDocument();
    expect(screen.getByText("status 200")).toBeInTheDocument();
    expect(screen.getByText("3 request headers")).toBeInTheDocument();
    expect(screen.getByText("1 response header")).toBeInTheDocument();
    expect(screen.getByText("1 SSE event")).toBeInTheDocument();
    expect(screen.getByText("session-id")).toBeInTheDocument();
    expect(screen.getAllByText("turn-http-1", { exact: false }).length).toBeGreaterThan(0);
    expect(screen.getByText("request body")).toBeInTheDocument();
    expect(screen.getByText("SSE event 1")).toBeInTheDocument();
    expect(screen.getAllByText("response.output_text.delta").length).toBeGreaterThan(0);
    expect(
      screen.getAllByText("Transport capture completed successfully.", { exact: false }).length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText(/websocket/i)).not.toBeInTheDocument();
  });

  it("uses an HTTP empty state when no SSE messages were captured", () => {
    render(
      <CodexTransportPanel
        transport={httpTransport({ messages: [] })}
        focusedMessageIndex={null}
      />,
    );

    expect(screen.getByText("No HTTP events captured")).toBeInTheDocument();
    expect(screen.queryByText("No websocket frames captured")).not.toBeInTheDocument();
  });
});
