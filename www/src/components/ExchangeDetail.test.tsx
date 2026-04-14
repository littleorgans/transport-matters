import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ExchangeDetail } from "./ExchangeDetail";

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
    response_ir: null,
  }),
  fetchOverrides: vi.fn().mockResolvedValue({ overrides: [], enabled: true }),
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

    await waitFor(() => expect(screen.getByText("claude-3")).toBeInTheDocument());
    expect(screen.getByText("anthropic")).toBeInTheDocument();
  });

  it("same-id re-render uses query cache — fetchExchange called once", async () => {
    const { fetchExchange } = await import("../api");
    const qc = makeClient();

    const { rerender } = render(
      <QueryClientProvider client={qc}>
        <ExchangeDetail id="exchange-001" />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(screen.getByText("claude-3")).toBeInTheDocument());
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
});
