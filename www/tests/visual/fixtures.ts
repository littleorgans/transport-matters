import type { Page } from "@playwright/test";
import type { ExchangeDetail, IndexEntry, PausedFlow } from "../../src/types";

// ── Deterministic time ──
// Playwright freezes the page clock to this instant so the elapsed timer,
// relative timestamps, and any `Date.now()`-derived state read the same
// on every run. Pick any stable point in time.
export const FROZEN_NOW = new Date("2026-04-14T10:00:00Z");

// Paused 3:28 ago — matches the elapsed value in the original screenshot.
const PAUSED_AT_MS = FROZEN_NOW.getTime() - 208_000;

export const mockPausedFlow: PausedFlow = {
  flow_id: "c740eb90-abcd-4321-9876-deadbeef0000",
  transport: "http",
  paused_at_ms: PAUSED_AT_MS,
  ir: {
    model: "claude-haiku-4-5-20251001",
    provider: "anthropic",
    system: [{ text: "you are a helpful assistant." }],
    tools: [],
    messages: [{ role: "user", content: [{ type: "text", text: "Hello there" }] }],
    sampling: {
      max_tokens: 32000,
      temperature: 1,
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
  original_system: [{ text: "you are a helpful assistant." }],
  original_messages: [{ role: "user", content: [{ type: "text", text: "Hello there" }] }],
  original_sampling: {
    max_tokens: 32000,
    temperature: 1,
    top_p: null,
    top_k: null,
    stop_sequences: [],
  },
  original_provider_extras: {},
  audit: null,
  tokens_before: null,
};

export const mockExchanges: IndexEntry[] = [
  {
    id: "aaaabbbb-1111-2222-3333-444455556666",
    ts: new Date(FROZEN_NOW.getTime() - 60_000).toISOString(),
    provider: "anthropic",
    model: "claude-sonnet-4-5",
    path: "",
    req: {
      system_parts: 1,
      system_chars: 29,
      tools_count: 4,
      tools_chars: 3_420,
      messages_count: 3,
      messages_chars: 8_551,
      total_chars: 12_000,
    },
    pipeline: null,
    res: {
      stop_reason: "end_turn",
      input_tokens: 3_208,
      output_tokens: 412,
      cache_creation_input_tokens: 0,
      cache_read_input_tokens: 1_144,
      text_chars: 1_982,
      tool_calls: 2,
    },
    mutated_manually: false,
  },
  {
    id: "ddddeeee-1111-2222-3333-444455556666",
    ts: new Date(FROZEN_NOW.getTime() - 600_000).toISOString(),
    provider: "openai",
    model: "gpt-4o",
    path: "",
    req: {
      system_parts: 1,
      system_chars: 41,
      tools_count: 2,
      tools_chars: 1_280,
      messages_count: 4,
      messages_chars: 6_479,
      total_chars: 7_800,
    },
    pipeline: null,
    res: {
      stop_reason: "end_turn",
      input_tokens: 2_112,
      output_tokens: 228,
      cache_creation_input_tokens: 0,
      cache_read_input_tokens: 0,
      text_chars: 1_131,
      tool_calls: 1,
    },
    mutated_manually: true,
  },
  {
    id: "ffff0000-1111-2222-3333-444455556666",
    ts: new Date(FROZEN_NOW.getTime() - 1_860_000).toISOString(),
    provider: "codex",
    model: "codex/gpt-5-codex",
    path: "runs/codex-session-01",
    req: {
      system_parts: 0,
      system_chars: 0,
      tools_count: 2,
      tools_chars: 842,
      messages_count: 2,
      messages_chars: 1_778,
      total_chars: 2_620,
    },
    pipeline: null,
    res: {
      stop_reason: "completed",
      input_tokens: 1_048,
      output_tokens: 164,
      cache_creation_input_tokens: 0,
      cache_read_input_tokens: 0,
      text_chars: 433,
      tool_calls: 0,
    },
    mutated_manually: false,
  },
  {
    id: "9999aaaa-1111-2222-3333-444455556666",
    ts: new Date(FROZEN_NOW.getTime() - 3_780_000).toISOString(),
    provider: "codex",
    model: "codex/transport-handshake",
    path: "runs/codex-session-02",
    req: {
      system_parts: 0,
      system_chars: 0,
      tools_count: 0,
      tools_chars: 0,
      messages_count: 1,
      messages_chars: 72,
      total_chars: 72,
    },
    pipeline: null,
    res: null,
    mutated_manually: false,
  },
];

export const mockCodexTransportSuccessId = mockExchanges[2].id;
export const mockCodexTransportDiagnosticId = mockExchanges[3].id;

// ── Exchange detail payloads ──
// Keyed by the `id` of the matching IndexEntry in `mockExchanges`. Lets a
// test preselect an exchange via localStorage and have the detail view render
// the full header without any backend.
export const mockExchangeDetails: Record<string, ExchangeDetail> = {
  "aaaabbbb-1111-2222-3333-444455556666": {
    entry: mockExchanges[0],
    request_ir: { model: "claude-sonnet-4-5", messages: [] },
    request_curated_ir: null,
    request_audit: null,
    response_ir: null,
    transport: null,
    transport_diagnostics: [],
  },
  "ddddeeee-1111-2222-3333-444455556666": {
    entry: mockExchanges[1],
    request_ir: { model: "gpt-4o", messages: [] },
    request_curated_ir: null,
    request_audit: null,
    response_ir: null,
    transport: null,
    transport_diagnostics: [],
  },
  "ffff0000-1111-2222-3333-444455556666": {
    entry: mockExchanges[2],
    request_ir: {
      model: "codex/gpt-5-codex",
      provider: "codex",
      messages: [
        {
          role: "user",
          content: [{ type: "text", text: "Summarize the websocket capture path." }],
        },
      ],
      tools: [
        {
          name: "shell",
          description: "Execute shell commands inside the workspace.",
          input_schema: { type: "object" },
        },
      ],
      stream: true,
      provider_extras: { type: "response.create" },
    },
    request_curated_ir: null,
    request_audit: null,
    response_ir: {
      status: "completed",
      output: [{ type: "output_text", text: "Transport capture completed successfully." }],
    },
    transport: {
      provider: "codex",
      protocol: "websocket",
      upgrade: {
        scheme: "wss",
        host: "chatgpt.com",
        path: "/backend-api/codex/responses?client=cli",
        request_headers: [
          { name: "origin", value: "https://chatgpt.com" },
          { name: "x-codex-session", value: "[redacted]" },
        ],
        response_status_code: 101,
        response_headers: [
          { name: "sec-websocket-accept", value: "fixture" },
          { name: "x-openai-proxy", value: "manicure" },
        ],
      },
      close: {
        close_code: 1000,
        close_reason: "done",
        closed_by_client: false,
        initial_client_frame_captured: true,
        client_message_count: 1,
        server_message_count: 2,
      },
      messages: [
        {
          direction: "client",
          is_text: true,
          size_bytes: 196,
          dropped: false,
          event_type: "response.create",
          payload_text:
            '{"type":"response.create","model":"gpt-5-codex","input":[{"role":"user","content":[{"type":"input_text","text":"Summarize the websocket capture path."}]}]}',
          payload_json: {
            type: "response.create",
            model: "gpt-5-codex",
            input: [
              {
                role: "user",
                content: [
                  {
                    type: "input_text",
                    text: "Summarize the websocket capture path.",
                  },
                ],
              },
            ],
          },
          payload_base64: null,
        },
        {
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
    transport_diagnostics: [],
  },
  "9999aaaa-1111-2222-3333-444455556666": {
    entry: mockExchanges[3],
    request_ir: {
      model: "codex/transport-handshake",
      provider: "codex",
      messages: [
        {
          role: "user",
          content: [{ type: "text", text: "Why did this websocket fail?" }],
        },
      ],
      tools: [],
      stream: true,
      provider_extras: { type: "response.create" },
    },
    request_curated_ir: null,
    request_audit: null,
    response_ir: null,
    transport: {
      provider: "codex",
      protocol: "websocket",
      upgrade: {
        scheme: "wss",
        host: "chatgpt.com",
        path: "/backend-api/codex/responses?client=cli",
        request_headers: [{ name: "origin", value: "https://chatgpt.com" }],
        response_status_code: 502,
        response_headers: [{ name: "content-type", value: "text/plain" }],
      },
      close: null,
      messages: [],
    },
    transport_diagnostics: [
      {
        severity: "error",
        code: "proxy_trust_failed",
        summary: "Proxy trust failed before the Codex websocket upgraded.",
        detail:
          "upgrade response status=502; content-type=text/plain; response body redacted (191 bytes; matched a proxy TLS trust failure signature)",
        operator_checks: [
          "Verify the managed Codex process inherited HTTP_PROXY and HTTPS_PROXY for the Manicure proxy.",
          "Verify CODEX_CA_CERTIFICATE points at a readable bundle that includes ~/.mitmproxy/mitmproxy-ca-cert.pem.",
          "Retry with `manicure codex --debug` and compare response.raw with the stored upgrade headers.",
        ],
      },
    ],
  },
};

export interface SetupOptions {
  /** Whether the breakpoint is armed. Default: true. */
  armed?: boolean;
  /** Whether a paused flow is active. Default: true. */
  paused?: boolean;
  /**
   * If set, preselects this exchange id via the persisted UI store so
   * `<ExchangeDetail>` renders for it immediately on load. The id must be a
   * key in `mockExchangeDetails`.
   */
  selectedExchangeId?: string;
}

/**
 * Wire up everything a visual test needs before navigating:
 *
 * - Freeze the page clock for deterministic elapsed-time rendering.
 * - Stub `EventSource` so the SSE "Live" indicator turns on without a backend.
 * - Intercept every `/api/**` request with canned responses derived from the
 *   mocks above, parametrised by `armed` / `paused`.
 *
 * Call this *before* `page.goto(...)`.
 */
export async function setupVisualTest(page: Page, opts: SetupOptions = {}): Promise<void> {
  const { armed = true, paused = true, selectedExchangeId } = opts;

  await page.clock.install({ time: FROZEN_NOW });

  await page.addInitScript((selectedId: string | undefined) => {
    class FakeEventSource extends EventTarget {
      static CONNECTING = 0;
      static OPEN = 1;
      static CLOSED = 2;
      readyState = 1;
      url: string;
      withCredentials = false;
      onopen: ((ev: Event) => void) | null = null;
      onerror: ((ev: Event) => void) | null = null;
      onmessage: ((ev: MessageEvent) => void) | null = null;
      constructor(url: string) {
        super();
        this.url = url;
        queueMicrotask(() => this.onopen?.(new Event("open")));
      }
      close() {
        this.readyState = 2;
      }
    }
    // biome-ignore lint/suspicious/noExplicitAny: replacing a global
    (window as any).EventSource = FakeEventSource;

    // Pre-populate the persisted UI store so a given exchange is selected on
    // first render — zustand's persist middleware reads this key at hydrate.
    if (selectedId) {
      localStorage.setItem("manicure-ui", JSON.stringify({ state: { selectedId }, version: 0 }));
    }
  }, selectedExchangeId);

  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const p = url.pathname;

    if (p === "/api/exchanges") {
      return route.fulfill({ json: mockExchanges });
    }
    if (p === "/api/breakpoint/status") {
      return route.fulfill({
        json: {
          mode: armed ? "armed_once" : "off",
          paused_flows: paused ? [{ flow_id: mockPausedFlow.flow_id }] : [],
        },
      });
    }
    if (p === `/api/breakpoint/paused/${mockPausedFlow.flow_id}`) {
      return route.fulfill({ json: mockPausedFlow });
    }
    if (p === "/api/overrides") {
      return route.fulfill({ json: { overrides: [], enabled: true } });
    }

    // /api/exchanges/{id} — per-exchange detail
    const detailMatch = p.match(/^\/api\/exchanges\/([^/]+)$/);
    if (detailMatch) {
      const id = decodeURIComponent(detailMatch[1]);
      const detail = mockExchangeDetails[id];
      if (detail) {
        return route.fulfill({ json: detail });
      }
      return route.fulfill({ status: 404, json: { error: "not found" } });
    }

    // Unknown route — return empty JSON so nothing throws.
    return route.fulfill({ json: {} });
  });
}
