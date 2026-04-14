import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ExchangeDetail, IndexEntry, PipelineStats } from "../../types";
import { ExchangeCard } from "./ExchangeCard";

vi.mock("../../api", () => ({
  fetchPipelineTokens: vi.fn(),
}));

function makeDetail(pipeline: PipelineStats | null): ExchangeDetail {
  const entry: IndexEntry = {
    id: "ex-1",
    ts: new Date().toISOString(),
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
      total_chars: 100,
    },
    pipeline,
    res: null,
    mutated_manually: false,
  };
  return {
    entry,
    request_ir: { model: "c-3", messages: [] } as unknown as ExchangeDetail["request_ir"],
    request_curated_ir: {
      model: "c-3",
      messages: [],
    } as unknown as ExchangeDetail["request_curated_ir"],
    response_ir: null,
  };
}

function renderCard(detail: ExchangeDetail) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ExchangeCard detail={detail} />
    </QueryClientProvider>,
  );
}

// The Pipeline tab is a button whose accessible name starts with "Pipeline"
// followed by a savedPct span. A regex name matcher picks it out without
// pinning on the current percent formatting.
const pipelineTabMatcher = { name: /pipeline/i };

describe("ExchangeCard pipeline tokens", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders stored pipeline tokens without hitting the lazy endpoint", async () => {
    const { fetchPipelineTokens } = await import("../../api");

    renderCard(
      makeDetail({
        overrides_applied: [],
        chars_before: 2048,
        chars_after: 1024,
        tokens_before: 250,
        tokens_after: 200,
      }),
    );
    fireEvent.click(screen.getByRole("button", pipelineTabMatcher));

    await waitFor(() => expect(screen.getByText("250")).toBeInTheDocument());
    expect(screen.getByText("200")).toBeInTheDocument();
    expect(screen.getByText("50")).toBeInTheDocument();
    // TokenStat suffixes "tokens" only in the token format. Chars stay bare.
    expect(screen.getAllByText("tokens").length).toBeGreaterThan(0);
    // Endpoint must not be called when the row is already stamped.
    expect(fetchPipelineTokens).not.toHaveBeenCalled();
  });

  it("keeps chars fallback when the lazy endpoint yields null tokens", async () => {
    const { fetchPipelineTokens } = await import("../../api");
    vi.mocked(fetchPipelineTokens).mockResolvedValue({
      tokens_before: null,
      tokens_after: null,
      reason: "counter_failed",
    });

    renderCard(
      makeDetail({
        overrides_applied: [],
        chars_before: 2048,
        chars_after: 1024,
        tokens_before: null,
        tokens_after: null,
      }),
    );
    fireEvent.click(screen.getByRole("button", pipelineTabMatcher));

    await waitFor(() => expect(fetchPipelineTokens).toHaveBeenCalledWith("ex-1"));
    // Chars format: 2048 → "2.0K", 1024 → "1.0K", saved 1024 → "1.0K".
    expect(screen.getAllByText("2.0K").length).toBeGreaterThan(0);
    expect(screen.getAllByText("1.0K").length).toBeGreaterThan(0);
    // No tokens suffix in chars mode. TokenStat's "chars" format leaves the
    // number bare so the absence of a "tokens" label signals the unit.
    expect(screen.queryByText("tokens")).toBeNull();
  });

  it("swaps chars for tokens once the lazy endpoint resolves", async () => {
    const { fetchPipelineTokens } = await import("../../api");
    vi.mocked(fetchPipelineTokens).mockResolvedValue({
      tokens_before: 333,
      tokens_after: 300,
      reason: null,
    });

    renderCard(
      makeDetail({
        overrides_applied: [],
        chars_before: 2048,
        chars_after: 1024,
        tokens_before: null,
        tokens_after: null,
      }),
    );
    fireEvent.click(screen.getByRole("button", pipelineTabMatcher));

    await waitFor(() => expect(screen.getByText("333")).toBeInTheDocument());
    expect(screen.getByText("300")).toBeInTheDocument();
    expect(screen.getByText("33")).toBeInTheDocument();
    expect(screen.getAllByText("tokens").length).toBeGreaterThan(0);
  });
});
