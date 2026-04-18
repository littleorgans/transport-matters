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
        messages: [],
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
      expect(screen.getByRole("button", { name: /transport/i })).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /transport/i }));
    expect(screen.getByText(/chatgpt rejected the codex websocket upgrade/i)).toBeInTheDocument();
    expect(screen.getByText(/Bearer \[redacted\]/i)).toBeInTheDocument();
    expect(screen.getByText(/response body redacted/i)).toBeInTheDocument();
    expect(screen.queryByText(/raw-secret/i)).not.toBeInTheDocument();
  });
});
