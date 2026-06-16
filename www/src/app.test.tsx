import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./app";
import { makeEntry } from "./components/__test-utils__/exchangeList";
import { useUIStore } from "./stores/uiStore";
import type { PausedFlow } from "./types";

let eventSourceUrls: string[];

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

beforeEach(() => {
  eventSourceUrls = [];
  vi.stubGlobal(
    "EventSource",
    class MockEventSource {
      onopen: (() => void) | null = null;
      onerror: (() => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      close = vi.fn();

      constructor(url: string | URL) {
        eventSourceUrls.push(String(url));
      }
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
        return Promise.resolve(
          makeJsonResponse([
            makeEntry({ id: "history-1", run_id: "run-current", path: "exchanges/history-1/" }),
          ]),
        );
      }
      if (url.endsWith("/v1/runs/run-current/exchanges/history-1")) {
        return Promise.resolve(
          makeJsonResponse({
            entry: makeEntry({
              id: "history-1",
              run_id: "run-current",
              path: "exchanges/history-1/",
            }),
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
      if (url.startsWith("/v1/runs/run-current/exchanges?")) {
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
    expect(screen.getByRole("heading", { name: "Transport Matters" })).toBeInTheDocument();
  });

  it("shows entry page when no exchanges", () => {
    renderWithProviders(<App />);
    expect(screen.getByText("Waiting for exchanges")).toBeInTheDocument();
  });

  it("opens the browser stream from the browser shell", async () => {
    renderWithProviders(<App />);

    await waitFor(() => expect(eventSourceUrls).toEqual(["/api/stream"]));
  });

  it("surfaces prior-run history from the waiting screen", async () => {
    renderWithProviders(<App />);

    fireEvent.click(screen.getByRole("button", { name: "Show history" }));

    await waitFor(() => {
      expect(screen.getByText("claude-sonnet-4-20250514")).toBeInTheDocument();
    });
    expect(screen.queryByText("prior")).not.toBeInTheDocument();
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

  it("anchors a paused subagent track from app state before its spawning exchange", async () => {
    const liveRows = [
      makeEntry({
        id: "parent-pre",
        run_id: "run-current",
        path: "exchanges/parent-pre/",
        track_id: "run-current",
        track_role: "parent",
        ts: "2026-04-26T00:00:00.000Z",
      }),
      makeEntry({
        id: "parent-spawn",
        run_id: "run-current",
        path: "exchanges/parent-spawn/",
        track_id: "run-current",
        track_role: "parent",
        ts: "2026-04-26T00:01:00.000Z",
      }),
      makeEntry({
        id: "parent-post",
        run_id: "run-current",
        path: "exchanges/parent-post/",
        track_id: "run-current",
        track_role: "parent",
        ts: "2026-04-26T00:02:00.000Z",
      }),
    ];
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
        if (url.startsWith("/v1/runs/run-current/exchanges?")) {
          return Promise.resolve(makeJsonResponse(liveRows));
        }
        return Promise.resolve(makeJsonResponse({}));
      }),
    );
    const pausedFlow: PausedFlow = {
      flow_id: "flow-pending",
      transport: "http",
      run_id: "run-current",
      track_id: "agent-pending",
      parent_track_id: "run-current",
      track_display_name: "pending-worker",
      track_role: "subagent",
      spawn_anchor: {
        track_spawn_exchange_id: "parent-spawn",
        track_spawn_tool_use_id: "toolu_pending",
        track_spawn_order: 0,
      },
      ir: {
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
        stream: false,
        provider_extras: {},
      },
      original_tools: [],
      original_system: [],
      original_messages: [],
      original_sampling: {
        max_tokens: 1024,
        temperature: null,
        top_p: null,
        top_k: null,
        stop_sequences: [],
      },
      original_provider_extras: {},
      audit: null,
      paused_at_ms: 1_700_000_000_000,
      tokens_before: null,
    };
    useUIStore.setState({ pausedFlow });

    renderWithProviders(<App />);

    await waitFor(() => {
      expect(screen.getByTestId("track-header-agent-pending")).toBeInTheDocument();
      expect(screen.getByTestId("exchange-row-parent-post")).toBeInTheDocument();
    });
    expect(
      Array.from(
        document.querySelectorAll<HTMLElement>(
          '[data-testid^="exchange-row-"], [data-testid^="track-header-"]',
        ),
        (element) => element.getAttribute("data-testid"),
      ),
    ).toEqual([
      "exchange-row-parent-post",
      "track-header-agent-pending",
      "exchange-row-parent-spawn",
      "exchange-row-parent-pre",
    ]);
    expect(screen.getByText("pending-worker")).toBeInTheDocument();
    expect(screen.getByText("pending")).toBeInTheDocument();
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
          return Promise.resolve(
            makeJsonResponse([
              makeEntry({ id: "history-1", run_id: "run-current", path: "exchanges/history-1/" }),
            ]),
          );
        }
        if (url.startsWith("/v1/runs/run-current/exchanges?")) {
          return Promise.resolve(
            makeJsonResponse([
              makeEntry({ id: "live-1", run_id: "run-current", path: "exchanges/live-1/" }),
            ]),
          );
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
