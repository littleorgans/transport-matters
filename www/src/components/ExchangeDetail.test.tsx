import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ExchangeDetail } from "./ExchangeDetail";

const mockMeta = {
  cwd: "/Users/alphab/Dev/LLM/DEV/helioy/attention-matters",
  workspaceId: "helioy/attention-matters",
  runId: "run-123",
};

// vi.mock is hoisted — factory must not reference module-level vars
vi.mock("../api", () => ({
  fetchExchange: vi.fn().mockResolvedValue({
    entry: {
      id: "exchange-001",
      ts: new Date("2026-01-01T12:00:00Z").toISOString(),
      provider: "anthropic",
      model: "anthropic/claude-3",
      path: "exchanges/test/",
      req: {
        system_parts: 0,
        system_chars: 0,
        tools_count: 0,
        tools_chars: 0,
        messages_count: 1,
        messages_chars: 10,
        total_chars: 10,
      },
      pipeline: null,
      res: null,
      mutated_manually: false,
    },
    request_ir: { model: "claude-3", messages: [] },
    request_curated_ir: null,
    request_audit: null,
    response_ir: null,
    transport: null,
    events: null,
    turn: null,
    transport_diagnostics: [],
  }),
  fetchOverrides: vi.fn().mockResolvedValue({ overrides: [], enabled: true }),
}));

vi.mock("../hooks/useMeta", () => ({
  useMeta: () => ({ meta: mockMeta, isLoading: false }),
}));

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

describe("ExchangeDetail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders exchange header after load", async () => {
    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <ExchangeDetail id="exchange-001" />
      </QueryClientProvider>,
    );

    await waitFor(() =>
      expect(
        screen.getByRole("heading", {
          name: /anthropic\s*\/\s*claude-3/i,
        }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("helioy/attention-matters")).toBeInTheDocument();
    expect(
      screen.getByTitle("/Users/alphab/Dev/LLM/DEV/helioy/attention-matters"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/frames/i)).not.toBeInTheDocument();
  });

  it("renders Codex turn telemetry as a provider-specific header row", async () => {
    const { fetchExchange } = await import("../api");
    vi.mocked(fetchExchange).mockResolvedValueOnce({
      entry: {
        id: "exchange-codex-header",
        ts: new Date("2026-01-01T12:00:00Z").toISOString(),
        provider: "codex",
        model: "codex/gpt-5-codex",
        path: "exchanges/test/",
        req: {
          system_parts: 0,
          system_chars: 0,
          tools_count: 0,
          tools_chars: 0,
          messages_count: 1,
          messages_chars: 10,
          total_chars: 10,
        },
        pipeline: null,
        res: {
          stop_reason: "completed",
          input_tokens: 0,
          output_tokens: 0,
          cache_creation_input_tokens: 0,
          cache_read_input_tokens: 0,
          text_chars: 41,
          tool_calls: 0,
        },
        mutated_manually: false,
      },
      request_ir: { model: "codex/gpt-5-codex", messages: [] },
      request_curated_ir: null,
      request_audit: null,
      response_ir: null,
      transport: null,
      events: [],
      turn: {
        turn_id: "turn-001",
        exchange_id: "exchange-codex-header",
        session_id: "ws-api",
        turn_index: 0,
        request_message_index: 0,
        terminal_message_index: 3,
        terminal_cause: "response_completed",
        message_range_start: 0,
        message_range_end: 3,
        model: "codex/gpt-5-codex",
        status: "completed",
        stop_reason: "completed",
        text_chars: 41,
        tool_calls: 0,
        started_at: new Date("2026-01-01T12:00:00Z").toISOString(),
        ended_at: new Date("2026-01-01T12:00:03Z").toISOString(),
        derivation_version: 1,
        cursor: null,
      },
      transport_diagnostics: [],
    });

    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <ExchangeDetail id="exchange-codex-header" />
      </QueryClientProvider>,
    );

    await waitFor(() =>
      expect(
        screen.getByRole("heading", {
          name: /codex\s*\/\s*gpt-5-codex/i,
        }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("helioy/attention-matters")).toBeInTheDocument();
    expect(screen.getByText("turn 0 completed")).toBeInTheDocument();
    expect(screen.getByText("frames 0 to 3")).toBeInTheDocument();
    expect(screen.getAllByText("41 chars").length).toBeGreaterThan(0);
  });

  it("same-id re-render uses query cache — fetchExchange called once", async () => {
    const { fetchExchange } = await import("../api");
    const qc = makeClient();

    const { rerender } = render(
      <QueryClientProvider client={qc}>
        <ExchangeDetail id="exchange-001" />
      </QueryClientProvider>,
    );

    await waitFor(() =>
      expect(
        screen.getByRole("heading", {
          name: /anthropic\s*\/\s*claude-3/i,
        }),
      ).toBeInTheDocument(),
    );
    expect(fetchExchange).toHaveBeenCalledTimes(1);

    // Re-render with same id — TanStack Query should serve from cache
    rerender(
      <QueryClientProvider client={qc}>
        <ExchangeDetail id="exchange-001" />
      </QueryClientProvider>,
    );

    expect(fetchExchange).toHaveBeenCalledTimes(1);
  });

  it("different id triggers a new fetch", async () => {
    const { fetchExchange } = await import("../api");
    const qc = makeClient();

    const { rerender } = render(
      <QueryClientProvider client={qc}>
        <ExchangeDetail id="exchange-001" />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(fetchExchange).toHaveBeenCalledTimes(1));

    rerender(
      <QueryClientProvider client={qc}>
        <ExchangeDetail id="exchange-002" />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(fetchExchange).toHaveBeenCalledTimes(2));
  });

  it("renders a transport tab when transport artifacts exist", async () => {
    const { fetchExchange } = await import("../api");
    vi.mocked(fetchExchange).mockResolvedValueOnce({
      entry: {
        id: "exchange-transport",
        ts: new Date("2026-01-01T12:00:00Z").toISOString(),
        provider: "codex",
        model: "codex/gpt-5-codex",
        path: "exchanges/test/",
        req: {
          system_parts: 0,
          system_chars: 0,
          tools_count: 0,
          tools_chars: 0,
          messages_count: 1,
          messages_chars: 10,
          total_chars: 10,
        },
        pipeline: null,
        res: {
          stop_reason: "completed",
          input_tokens: 0,
          output_tokens: 0,
          cache_creation_input_tokens: 0,
          cache_read_input_tokens: 0,
          text_chars: 5,
          tool_calls: 0,
        },
        mutated_manually: false,
      },
      request_ir: { model: "codex/gpt-5-codex", messages: [] },
      request_curated_ir: null,
      request_audit: null,
      response_ir: null,
      transport: {
        provider: "codex",
        protocol: "websocket",
        upgrade: {
          scheme: "wss",
          host: "chatgpt.com",
          path: "/backend-api/codex/responses",
          request_headers: [{ name: "authorization", value: "Bearer [redacted]" }],
          response_status_code: 101,
          response_headers: [],
        },
        close: null,
        messages: [
          {
            ts: new Date("2026-01-01T12:00:00Z").toISOString(),
            direction: "client",
            is_text: true,
            size_bytes: 96,
            dropped: false,
            event_type: "response.create",
            payload_text: '{"type":"response.create","model":"gpt-5-codex"}',
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
            payload_text:
              '{"type":"response.output_text.delta","delta":"Transport capture completed successfully."}',
            payload_json: {
              type: "response.output_text.delta",
              delta: "Transport capture completed successfully.",
            },
            payload_base64: null,
          },
          {
            ts: new Date("2026-01-01T12:00:02Z").toISOString(),
            direction: "server",
            is_text: true,
            size_bytes: 62,
            dropped: false,
            event_type: "response.completed",
            payload_text: '{"type":"response.completed","response":{"status":"completed"}}',
            payload_json: {
              type: "response.completed",
              response: { status: "completed" },
            },
            payload_base64: null,
          },
        ],
      },
      events: [
        {
          event_id: "evt_000001",
          exchange_id: "exchange-transport",
          session_id: "ws-api",
          turn_id: "turn-001",
          seq: 1,
          ts: new Date("2026-01-01T12:00:00Z").toISOString(),
          source: "client",
          kind: "turn_started",
          transport_ref: { message_index: 0 },
          data: {},
          derivation_version: 1,
        },
        {
          event_id: "evt_000002",
          exchange_id: "exchange-transport",
          session_id: "ws-api",
          turn_id: "turn-001",
          seq: 2,
          ts: new Date("2026-01-01T12:00:01Z").toISOString(),
          source: "server",
          kind: "assistant_item_completed",
          transport_ref: { message_index: 1 },
          data: {
            item_id: "msg_01",
            item_type: "message",
            phase: "final_answer",
            role: "assistant",
            text_chars: 41,
          },
          derivation_version: 1,
        },
        {
          event_id: "evt_000003",
          exchange_id: "exchange-transport",
          session_id: "ws-api",
          turn_id: "turn-001",
          seq: 3,
          ts: new Date("2026-01-01T12:00:02Z").toISOString(),
          source: "proxy",
          kind: "turn_finalized",
          transport_ref: null,
          data: {
            status: "completed",
            stop_reason: "completed",
            terminal_cause: "response_completed",
            text_chars: 41,
            tool_calls: 0,
          },
          derivation_version: 1,
        },
      ],
      turn: {
        turn_id: "turn-001",
        exchange_id: "exchange-transport",
        session_id: "ws-api",
        turn_index: 1,
        request_message_index: 0,
        terminal_message_index: 2,
        terminal_cause: "response_completed",
        message_range_start: 0,
        message_range_end: 2,
        model: "codex/gpt-5-codex",
        status: "completed",
        stop_reason: "completed",
        text_chars: 41,
        tool_calls: 0,
        started_at: new Date("2026-01-01T12:00:00Z").toISOString(),
        ended_at: new Date("2026-01-01T12:00:02Z").toISOString(),
        derivation_version: 1,
        cursor: null,
      },
      transport_diagnostics: [
        {
          severity: "error",
          code: "chatgpt_auth_rejected",
          summary: "ChatGPT rejected the Codex websocket upgrade.",
          detail:
            "upgrade response status=403; content-type=application/json; response body redacted (58 bytes; status indicates an upstream auth challenge)",
          operator_checks: ["Confirm Codex is authenticated with ChatGPT."],
        },
      ],
    });

    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <ExchangeDetail id="exchange-transport" />
      </QueryClientProvider>,
    );

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /timeline/i })).toBeInTheDocument(),
    );
    expect(screen.getByText(/Client sent response.create to open the turn/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /jump to transport frame 1/i }));
    await waitFor(() => expect(screen.getByText(/Raw transport JSON/i)).toBeInTheDocument());
    expect(screen.getByText(/status 101/i).closest("div")).not.toHaveTextContent(/\bclose\b/i);
    expect(screen.getAllByText(/response\.output_text\.delta/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Transport capture completed successfully/i).length).toBeGreaterThan(
      0,
    );
    expect(screen.getByText(/chatgpt rejected the codex websocket upgrade/i)).toBeInTheDocument();
    expect(screen.getByText(/Bearer \[redacted\]/i)).toBeInTheDocument();
    expect(screen.getByText(/response body redacted/i)).toBeInTheDocument();
    expect(screen.queryByText(/raw-secret/i)).not.toBeInTheDocument();
  });

  it("renders open Codex turns from turn status without inventing terminal events", async () => {
    const { fetchExchange } = await import("../api");
    vi.mocked(fetchExchange).mockResolvedValueOnce({
      entry: {
        id: "exchange-open",
        ts: new Date("2026-01-01T12:00:00Z").toISOString(),
        provider: "codex",
        model: "codex/gpt-5-codex",
        path: "exchanges/test/",
        req: {
          system_parts: 0,
          system_chars: 0,
          tools_count: 1,
          tools_chars: 0,
          messages_count: 1,
          messages_chars: 10,
          total_chars: 10,
        },
        pipeline: null,
        res: null,
        mutated_manually: false,
      },
      request_ir: { model: "codex/gpt-5-codex", messages: [] },
      request_curated_ir: null,
      request_audit: null,
      response_ir: null,
      transport: {
        provider: "codex",
        protocol: "websocket",
        upgrade: {
          scheme: "wss",
          host: "chatgpt.com",
          path: "/backend-api/codex/responses",
          request_headers: [],
          response_status_code: 101,
          response_headers: [],
        },
        close: null,
        messages: [
          {
            ts: new Date("2026-01-01T12:00:00Z").toISOString(),
            direction: "client",
            is_text: true,
            size_bytes: 96,
            dropped: false,
            event_type: "response.create",
            payload_text: '{"type":"response.create","model":"gpt-5-codex"}',
            payload_json: { type: "response.create", model: "gpt-5-codex" },
            payload_base64: null,
          },
        ],
      },
      events: [
        {
          event_id: "evt_000001",
          exchange_id: "exchange-open",
          session_id: "ws-open",
          turn_id: "turn-open",
          seq: 1,
          ts: new Date("2026-01-01T12:00:00Z").toISOString(),
          source: "client",
          kind: "turn_started",
          transport_ref: { message_index: 0 },
          data: {},
          derivation_version: 1,
        },
      ],
      turn: {
        turn_id: "turn-open",
        exchange_id: "exchange-open",
        session_id: "ws-open",
        turn_index: 4,
        request_message_index: 0,
        terminal_message_index: null,
        terminal_cause: null,
        message_range_start: 0,
        message_range_end: 0,
        model: "codex/gpt-5-codex",
        status: "open",
        stop_reason: null,
        text_chars: 12,
        tool_calls: 0,
        started_at: new Date("2026-01-01T12:00:00Z").toISOString(),
        ended_at: null,
        derivation_version: 1,
        cursor: {
          next_message_index: 1,
          next_seq: 2,
          open_assistant_items: {
            msg_partial: { text: "hello world" },
          },
          open_tool_calls: {
            call_partial: { arguments: '{"path":"README.md"}' },
          },
          terminal_seen: false,
        },
      },
      transport_diagnostics: [],
    });

    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <ExchangeDetail id="exchange-open" />
      </QueryClientProvider>,
    );

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /timeline/i })).toBeInTheDocument(),
    );
    expect(screen.getByText(/live state/i)).toBeInTheDocument();
    expect(screen.getByText(/next frame 1/i)).toBeInTheDocument();
    expect(screen.queryByText(/Turn finalized as/i)).not.toBeInTheDocument();
  });

  it("shows a repaired timeline for legacy Codex exchanges repaired on read", async () => {
    const { fetchExchange } = await import("../api");
    vi.mocked(fetchExchange).mockResolvedValueOnce({
      entry: {
        id: "exchange-legacy",
        ts: new Date("2026-01-01T12:00:00Z").toISOString(),
        provider: "codex",
        model: "codex/gpt-5-codex",
        path: "exchanges/test/",
        req: {
          system_parts: 0,
          system_chars: 0,
          tools_count: 0,
          tools_chars: 0,
          messages_count: 1,
          messages_chars: 10,
          total_chars: 10,
        },
        pipeline: null,
        res: null,
        mutated_manually: false,
      },
      request_ir: { model: "codex/gpt-5-codex", messages: [] },
      request_curated_ir: null,
      request_audit: null,
      response_ir: null,
      transport: {
        provider: "codex",
        protocol: "websocket",
        upgrade: {
          scheme: "wss",
          host: "chatgpt.com",
          path: "/backend-api/codex/responses",
          request_headers: [],
          response_status_code: 101,
          response_headers: [],
        },
        close: null,
        messages: [
          {
            ts: new Date("2026-01-01T12:00:00Z").toISOString(),
            direction: "client",
            is_text: true,
            size_bytes: 96,
            dropped: false,
            event_type: "response.create",
            payload_text: '{"type":"response.create","model":"gpt-5-codex"}',
            payload_json: { type: "response.create", model: "gpt-5-codex" },
            payload_base64: null,
          },
        ],
      },
      events: [
        {
          event_id: "evt-1",
          exchange_id: "exchange-legacy",
          session_id: "sess-1",
          turn_id: "exchange-legacy",
          seq: 1,
          ts: new Date("2026-01-01T12:00:00Z").toISOString(),
          source: "client",
          kind: "turn_started",
          transport_ref: { message_index: 0 },
          data: {},
          derivation_version: 1,
        },
      ],
      turn: {
        turn_id: "exchange-legacy",
        exchange_id: "exchange-legacy",
        session_id: "sess-1",
        turn_index: 0,
        request_message_index: 0,
        terminal_message_index: null,
        terminal_cause: null,
        message_range_start: 0,
        message_range_end: 0,
        model: "codex/gpt-5-codex",
        status: "open",
        stop_reason: null,
        text_chars: 0,
        tool_calls: 0,
        started_at: new Date("2026-01-01T12:00:00Z").toISOString(),
        ended_at: null,
        derivation_version: 1,
        cursor: {
          next_message_index: 1,
          next_seq: 2,
          open_assistant_items: {},
          open_tool_calls: {},
          terminal_seen: false,
        },
      },
      codex_derived_artifacts: {
        status: "supported",
        diagnostics: [
          {
            severity: "info",
            code: "codex_derived_missing",
            summary: "No persisted Codex derived artifacts were found.",
            detail: null,
          },
        ],
        repair: {
          action: "repaired",
          status_before: "missing",
        },
      },
      transport_diagnostics: [],
    });

    const qc = makeClient();
    render(
      <QueryClientProvider client={qc}>
        <ExchangeDetail id="exchange-legacy" />
      </QueryClientProvider>,
    );

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /timeline/i })).toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: /inspect/i })).not.toBeInTheDocument();
    expect(screen.getByText(/Client sent response.create to open the turn/i)).toBeInTheDocument();
    expect(
      screen.getByText(/semantic timeline rebuilt from canonical transport during read/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/repaired from missing/i)).toBeInTheDocument();
    expect(
      screen.getByText(/no persisted codex derived artifacts were found/i),
    ).toBeInTheDocument();

    const transportTab = screen.getAllByRole("button", { name: /transport/i }).at(0);
    if (transportTab == null) {
      throw new Error("transport tab missing");
    }
    fireEvent.click(transportTab);
    await waitFor(() => expect(screen.getByText(/Raw transport JSON/i)).toBeInTheDocument());
  });
});
