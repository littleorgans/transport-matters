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
  audit: null,
};

export const mockExchanges: IndexEntry[] = [
  {
    id: "aaaabbbb-1111-2222-3333-444455556666",
    ts: new Date(FROZEN_NOW.getTime() - 60_000).toISOString(),
    provider: "anthropic",
    model: "claude-sonnet-4-5",
    path: "",
    req: { tools_count: 4, total_chars: 12_000 },
    pipeline: null,
    res: { stop_reason: "end_turn", output_tokens: 412 },
    mutated_manually: false,
  },
  {
    id: "ddddeeee-1111-2222-3333-444455556666",
    ts: new Date(FROZEN_NOW.getTime() - 600_000).toISOString(),
    provider: "openai",
    model: "gpt-4o",
    path: "",
    req: { tools_count: 2, total_chars: 7_800 },
    pipeline: null,
    res: { stop_reason: "end_turn", output_tokens: 228 },
    mutated_manually: true,
  },
];

// ── Exchange detail payloads ──
// Keyed by the `id` of the matching IndexEntry in `mockExchanges`. Lets a
// test preselect an exchange via localStorage and have the detail view render
// the full header without any backend.
export const mockExchangeDetails: Record<string, ExchangeDetail> = {
  "aaaabbbb-1111-2222-3333-444455556666": {
    entry: mockExchanges[0],
    request_ir: { model: "claude-sonnet-4-5", messages: [] },
    request_curated_ir: null,
    response_ir: null,
  },
  "ddddeeee-1111-2222-3333-444455556666": {
    entry: mockExchanges[1],
    request_ir: { model: "gpt-4o", messages: [] },
    request_curated_ir: null,
    response_ir: null,
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
