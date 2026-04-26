import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./app";
import { useUIStore } from "./stores/uiStore";

function renderWithProviders(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

function makeJsonResponse(data: unknown): Response {
  return new Response(JSON.stringify(data), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function makeEntry(id: string, runId: string) {
  return {
    id,
    run_id: runId,
    ts: new Date().toISOString(),
    provider: "anthropic",
    model: "anthropic/claude-sonnet-4-20250514",
    path: `exchanges/${id}/`,
    req: {
      system_parts: 0,
      system_chars: 0,
      tools_count: 1,
      tools_chars: 12,
      messages_count: 1,
      messages_chars: 42,
      total_chars: 54,
    },
    pipeline: null,
    res: null,
    mutated_manually: false,
  };
}

beforeEach(() => {
  vi.stubGlobal(
    "EventSource",
    class MockEventSource {
      onopen: (() => void) | null = null;
      onerror: (() => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      close = vi.fn();
    },
  );
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string | URL | Request) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url === "/api/meta") {
        return Promise.resolve(
          makeJsonResponse({
            cwd: "/tmp/project",
            workspace_id: "workspace-1",
            run_id: "run-current",
          }),
        );
      }
      if (url.includes("include_history=true")) {
        return Promise.resolve(makeJsonResponse([makeEntry("history-1", "run-old")]));
      }
      if (url.endsWith("/api/exchanges/history-1")) {
        return Promise.resolve(
          makeJsonResponse({
            entry: makeEntry("history-1", "run-old"),
            request_ir: {
              model: "anthropic/claude-sonnet-4-20250514",
              provider: "anthropic",
              system: [],
              tools: [],
              messages: [],
              sampling: {
                max_tokens: 1024,
                temperature: null,
                top_p: null,
                top_k: null,
                stop_sequences: [],
              },
              metadata: {
                session_id: null,
                device_id: null,
                account_id: null,
                provider_metadata: {},
              },
              stream: true,
              provider_extras: {},
            },
            request_curated_ir: null,
            request_audit: null,
            response_ir: null,
            transport: null,
            transport_diagnostics: [],
          }),
        );
      }
      if (url.startsWith("/api/exchanges?")) {
        return Promise.resolve(makeJsonResponse([]));
      }
      return Promise.resolve(makeJsonResponse({}));
    }),
  );
  // Reset store between tests
  useUIStore.setState({ pausedFlow: null, selectedId: null, includeHistory: false });
  localStorage.clear();
});

describe("App", () => {
  it("renders the app title", () => {
    renderWithProviders(<App />);
    expect(screen.getByRole("heading", { name: "Manicure" })).toBeInTheDocument();
  });

  it("shows entry page when no exchanges", () => {
    renderWithProviders(<App />);
    expect(screen.getByText("Waiting for exchanges")).toBeInTheDocument();
  });

  it("surfaces prior-run history from the waiting screen", async () => {
    renderWithProviders(<App />);

    fireEvent.click(screen.getByRole("button", { name: "Show history" }));

    await waitFor(() => {
      expect(screen.getByText("claude-sonnet-4-20250514")).toBeInTheDocument();
    });
    expect(screen.getByText("prior")).toBeInTheDocument();
  });

  it("keeps a persisted prior-run selection latent until history is re-enabled", async () => {
    useUIStore.setState({ selectedId: "history-1", includeHistory: false });

    renderWithProviders(<App />);

    expect(screen.getByText("Waiting for exchanges")).toBeInTheDocument();
    expect(useUIStore.getState().selectedId).toBe("history-1");

    fireEvent.click(screen.getByRole("button", { name: "Show history" }));

    await waitFor(() => {
      expect(screen.getByText("claude-sonnet-4-20250514")).toBeInTheDocument();
    });
    expect(useUIStore.getState().selectedId).toBe("history-1");
  });

  it("preserves a hidden prior-run selection across history toggles", async () => {
    useUIStore.setState({ selectedId: "history-1", includeHistory: true });

    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getByText("claude-sonnet-4-20250514")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("switch", { name: "Show prior runs" }));

    expect(screen.getByText("Waiting for exchanges")).toBeInTheDocument();
    expect(useUIStore.getState().selectedId).toBe("history-1");

    fireEvent.click(screen.getByRole("button", { name: "Show history" }));

    await waitFor(() => {
      expect(screen.getByText("claude-sonnet-4-20250514")).toBeInTheDocument();
    });
    expect(useUIStore.getState().selectedId).toBe("history-1");
  });

  it("clears a stale hidden selection that no longer exists in history", async () => {
    useUIStore.setState({ selectedId: "missing-1", includeHistory: false });
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string | URL | Request) => {
        const url =
          typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
        if (url === "/api/meta") {
          return Promise.resolve(
            makeJsonResponse({
              cwd: "/tmp/project",
              workspace_id: "workspace-1",
              run_id: "run-current",
            }),
          );
        }
        if (url.includes("include_history=true")) {
          return Promise.resolve(makeJsonResponse([makeEntry("history-1", "run-old")]));
        }
        if (url.startsWith("/api/exchanges?")) {
          return Promise.resolve(makeJsonResponse([makeEntry("live-1", "run-current")]));
        }
        return Promise.resolve(makeJsonResponse({}));
      }),
    );

    renderWithProviders(<App />);

    await waitFor(() => {
      expect(useUIStore.getState().selectedId).toBeNull();
    });
    expect(screen.getByText("Select an exchange to inspect")).toBeInTheDocument();
    expect(screen.queryByText(/outside the live session view/i)).not.toBeInTheDocument();
  });
});
