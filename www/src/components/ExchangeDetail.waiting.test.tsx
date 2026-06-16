import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchExchange } from "../api";
import { exchangeKey } from "../lib/queryKeys";
import {
  detailResStats,
  makeExchangeDetail,
  openCodexTurnListSummary,
} from "./__test-utils__/exchangeDetail";
import { ExchangeDetail } from "./ExchangeDetail";

vi.mock("../api", () => ({
  fetchExchange: vi.fn(),
}));

vi.mock("../hooks/useMeta", () => ({
  useMeta: () => ({
    meta: {
      cwd: "/Users/alphab/Dev/LLM/DEV/helioy/attention-matters",
      workspaceId: "helioy/attention-matters",
      runId: "run-123",
    },
    isLoading: false,
  }),
}));

function makeClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderDetail(id: string, client = makeClient()) {
  render(
    <QueryClientProvider client={client}>
      <ExchangeDetail runId="run-current" id={id} />
    </QueryClientProvider>,
  );
  return client;
}

describe("ExchangeDetail waiting affordance", () => {
  const mockFetchExchange = vi.mocked(fetchExchange);

  beforeEach(() => {
    vi.resetAllMocks();
    mockFetchExchange.mockResolvedValue(makeExchangeDetail());
  });

  it("renders a waiting chip for HTTP provisional detail rows", async () => {
    mockFetchExchange.mockResolvedValueOnce(makeExchangeDetail({ entry: { id: "http-pending" } }));

    renderDetail("http-pending");

    expect(await screen.findByTestId("exchange-detail-waiting")).toHaveTextContent(
      "AWAITING RESPONSE",
    );
  });

  it("clears the waiting chip when the detail row finalizes", async () => {
    mockFetchExchange
      .mockResolvedValueOnce(makeExchangeDetail({ entry: { id: "http-transition" } }))
      .mockResolvedValueOnce(
        makeExchangeDetail({
          entry: { id: "http-transition", res: detailResStats },
          response_ir: { status: "completed" },
        }),
      );

    const client = renderDetail("http-transition");

    expect(await screen.findByTestId("exchange-detail-waiting")).toBeInTheDocument();
    await client.invalidateQueries({ queryKey: exchangeKey("run-current", "http-transition") });
    await waitFor(() => expect(screen.queryByTestId("exchange-detail-waiting")).toBeNull());
    expect(screen.getByRole("button", { name: /response/i })).toBeEnabled();
  });

  it("does not render the waiting chip for open Codex rows with entry turn state", async () => {
    mockFetchExchange.mockResolvedValueOnce(
      makeExchangeDetail({
        entry: {
          id: "codex-open",
          provider: "codex",
          codex_turn: openCodexTurnListSummary,
        },
      }),
    );

    renderDetail("codex-open");

    await screen.findByRole("heading", { name: /codex\s*\/\s*gpt-5-codex/i });
    expect(screen.queryByTestId("exchange-detail-waiting")).toBeNull();
  });

  it("renders a waiting chip for Codex provisional detail rows without entry turn state", async () => {
    mockFetchExchange.mockResolvedValueOnce(
      makeExchangeDetail({ entry: { id: "codex-pending", provider: "codex" } }),
    );

    renderDetail("codex-pending");

    expect(await screen.findByTestId("exchange-detail-waiting")).toHaveTextContent(
      "AWAITING RESPONSE",
    );
  });
});
