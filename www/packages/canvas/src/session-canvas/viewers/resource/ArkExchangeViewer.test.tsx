import { fireEvent, screen, waitFor } from "@testing-library/react";
import type { ExchangeDetail } from "@tm/core/types/exchanges";
import { afterEach, describe, expect, it } from "vitest";
import {
  installMockTransport,
  jsonResponse,
  renderWithQuery,
  restoreTransport,
} from "../../testUtils";
import { ArkExchangeViewer, toDetailTab } from "./ArkExchangeViewer";

const RUN_ID = "run-current";
const EXCHANGE_ID = "ex-1";

/** Content-rich detail payload exercising every tab the inspector shows. */
function makeDetail(overrides: Partial<ExchangeDetail> = {}): ExchangeDetail {
  return {
    entry: {
      id: EXCHANGE_ID,
      ts: "2026-04-14T10:08:55Z",
      provider: "anthropic",
      model: "claude-sonnet-4-5",
      req: { messages_count: 2, total_chars: 1200 },
      res: { input_tokens: 900, output_tokens: 42 },
      mutated_manually: false,
    },
    request_ir: {
      model: "claude-sonnet-4-5",
      system: [{ type: "text", text: "You are a careful reviewer." }],
      messages: [{ role: "user", content: [{ type: "text", text: "Review the capture path." }] }],
      tools: [
        { name: "shell", description: "Run shell commands.", input_schema: { type: "object" } },
      ],
    },
    request_curated_ir: null,
    request_audit: null,
    response_ir: {
      content: [{ type: "text", text: "The capture path looks correct." }],
    },
    transport: null,
    transport_diagnostics: [],
    ...overrides,
  } as unknown as ExchangeDetail;
}

function installDetail(detail: ExchangeDetail): void {
  installMockTransport((path) => {
    if (path === `/v1/runs/${RUN_ID}/exchanges/${EXCHANGE_ID}`) return jsonResponse(detail);
    return jsonResponse({ error: "not found" }, 404);
  });
}

async function renderViewer(detail: ExchangeDetail, initialView?: string | null): Promise<void> {
  installDetail(detail);
  renderWithQuery(
    <ArkExchangeViewer exchangeId={EXCHANGE_ID} initialView={initialView} runId={RUN_ID} />,
  );
  await screen.findByRole("heading", { level: 2 });
}

afterEach(restoreTransport);

describe("toDetailTab", () => {
  it.each([
    ["request", "request"],
    ["response", "response"],
    ["diagnostics", "transport"],
    ["events", "inspect"],
    [null, "inspect"],
    [undefined, "inspect"],
  ] as const)("maps initialView %s to the %s tab", (view, tab) => {
    expect(toDetailTab(view)).toBe(tab);
  });
});

describe("ArkExchangeViewer render contract", () => {
  it("renders the exchange header identity", async () => {
    await renderViewer(makeDetail());
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(
      "anthropic / claude-sonnet-4-5",
    );
  });

  it("renders all four tabs and selects inspect by default", async () => {
    await renderViewer(makeDetail());
    const tabs = screen.getAllByRole("tab").map((tab) => tab.textContent);
    expect(tabs.join(" ")).toMatch(/inspect/i);
    expect(tabs.join(" ")).toMatch(/request/i);
    expect(tabs.join(" ")).toMatch(/response/i);
    expect(tabs.join(" ")).toMatch(/transport/i);
    expect(screen.getByRole("tab", { selected: true })).toHaveTextContent(/inspect/i);
  });

  it("shows the inspector's inspect-tab content: system, messages, response, tools", async () => {
    await renderViewer(makeDetail());
    expect(screen.getByText("Review the capture path.")).toBeInTheDocument();
    expect(screen.getByText("You are a careful reviewer.")).toBeInTheDocument();
    expect(screen.getByText("The capture path looks correct.")).toBeInTheDocument();
    expect(screen.getByText("Run shell commands.")).toBeInTheDocument();
  });

  it("opens the tab mapped from initialView", async () => {
    await renderViewer(makeDetail(), "request");
    expect(screen.getByRole("tab", { selected: true })).toHaveTextContent(/request/i);
  });

  it("disables the response tab when there is no response payload", async () => {
    await renderViewer(makeDetail({ response_ir: null }));
    expect(screen.getByRole("tab", { name: /response/i })).toBeDisabled();
  });

  it("disables the transport tab when there are no transport artifacts", async () => {
    await renderViewer(makeDetail({ transport: null }));
    expect(screen.getByRole("tab", { name: /transport/i })).toBeDisabled();
  });

  it("switches to the request payload on tab click", async () => {
    await renderViewer(makeDetail());
    fireEvent.click(screen.getByRole("tab", { name: /request/i }));
    await waitFor(() => {
      expect(screen.getByRole("tab", { selected: true })).toHaveTextContent(/request/i);
    });
  });

  it("renders transport diagnostics content", async () => {
    await renderViewer(
      makeDetail({
        transport: {
          provider: "codex",
          protocol: "websocket",
          messages: [],
          upgrade: {},
          close: null,
        },
        transport_diagnostics: [
          {
            severity: "warning",
            code: "ws-frame-gap",
            summary: "Frames dropped during capture.",
            detail: "The proxy restarted mid-turn.",
            operator_checks: ["Check shared proxy logs."],
          },
        ],
      } as unknown as Partial<ExchangeDetail>),
      "diagnostics",
    );
    expect(screen.getByRole("tab", { selected: true })).toHaveTextContent(/transport/i);
    expect(screen.getByText("Frames dropped during capture.")).toBeInTheDocument();
  });

  it("stays read-only: no download or edit affordances", async () => {
    await renderViewer(makeDetail({ entry: { ...makeDetail().entry, mutated_manually: true } }));
    expect(screen.queryByRole("button", { name: /download/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/edited/i)).not.toBeInTheDocument();
  });

  it("opens and closes the inspect fullscreen overlay", async () => {
    await renderViewer(makeDetail());
    fireEvent.click(screen.getByRole("button", { name: /open inspect fullscreen/i }));
    const close = screen.getByRole("button", { name: /close inspect fullscreen/i });
    expect(close).toBeInTheDocument();
    fireEvent.click(close);
    expect(
      screen.queryByRole("button", { name: /close inspect fullscreen/i }),
    ).not.toBeInTheDocument();
  });

  it("offers fullscreen on the inspect tab only", async () => {
    await renderViewer(makeDetail(), "request");
    expect(
      screen.queryByRole("button", { name: /open inspect fullscreen/i }),
    ).not.toBeInTheDocument();
  });

  it("shows the curated request as sent, with a curated signal, when the request was mutated", async () => {
    await renderViewer(
      makeDetail({
        request_curated_ir: {
          model: "claude-sonnet-4-5",
          system: [{ type: "text", text: "You are a careful reviewer." }],
          messages: [{ role: "user", content: [{ type: "text", text: "Curated capture ask." }] }],
          tools: [],
        },
      } as unknown as Partial<ExchangeDetail>),
    );
    expect(screen.getByText("Curated capture ask.")).toBeInTheDocument();
    expect(screen.queryByText("Review the capture path.")).not.toBeInTheDocument();
    expect(screen.getByText(/as sent/i)).toBeInTheDocument();
  });

  it("shows no curated signal when the request was never mutated", async () => {
    await renderViewer(makeDetail());
    expect(screen.queryByText(/as sent/i)).not.toBeInTheDocument();
  });

  it("renders codex derived-artifacts diagnostics as operator warnings", async () => {
    await renderViewer(
      makeDetail({
        codex_derived_artifacts: {
          status: "missing",
          diagnostics: [
            {
              severity: "warning",
              code: "sidecar-missing",
              summary: "Semantic sidecars were not persisted for this turn.",
              detail: "Timeline rebuilt from canonical transport.",
            },
          ],
          repair: null,
        },
      } as unknown as Partial<ExchangeDetail>),
    );
    expect(
      screen.getByText("Semantic sidecars were not persisted for this turn."),
    ).toBeInTheDocument();
    expect(screen.getByText("missing")).toBeInTheDocument();
  });

  it("labels a repaired derived-artifacts state by its prior status", async () => {
    await renderViewer(
      makeDetail({
        codex_derived_artifacts: {
          status: "supported",
          diagnostics: [],
          repair: { action: "repaired", status_before: "inconsistent" },
        },
      } as unknown as Partial<ExchangeDetail>),
    );
    expect(screen.getByText("repaired from inconsistent")).toBeInTheDocument();
  });

  it("hides the derived-artifacts section when the state carries no signal", async () => {
    await renderViewer(
      makeDetail({
        codex_derived_artifacts: { status: "supported", diagnostics: [], repair: null },
      } as unknown as Partial<ExchangeDetail>),
    );
    expect(screen.queryByText(/semantic timeline/i)).not.toBeInTheDocument();
  });

  it("renders the fetch error body when the exchange is missing", async () => {
    installMockTransport(() => jsonResponse({ error: "not found" }, 404));
    renderWithQuery(<ArkExchangeViewer exchangeId="gone" initialView={null} runId={RUN_ID} />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("marks a response-less exchange as awaiting response", async () => {
    await renderViewer(
      makeDetail({
        entry: {
          ...makeDetail().entry,
          res: null,
        },
        response_ir: null,
      } as unknown as Partial<ExchangeDetail>),
    );
    expect(screen.getByText(/awaiting response/i)).toBeInTheDocument();
  });
});
