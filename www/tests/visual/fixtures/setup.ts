import type { Page, Route } from "@playwright/test";
import { FRONTEND_STORAGE_KEYS } from "../../../src/stores/persistence";
import type { IndexEntry } from "../../../src/types";
import { mockExchangeDetails } from "./details";
import { mockExchanges, mockVisualRunId } from "./exchanges";
import { mockPausedFlow } from "./pausedFlow";
import { FROZEN_NOW } from "./time";

const MOCK_META = {
  cwd: "/Users/alphab/Dev/LLM/DEV/helioy/transport-matters-worktrees/nancy-ALP-1847",
  workspace_id: "helioy/nancy-ALP-1847",
  run_id: mockVisualRunId,
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
  /** Exchange list fixture returned from `/v1/runs/{runId}/exchanges`. Default: `mockExchanges`. */
  exchanges?: readonly IndexEntry[];
}

/**
 * Wire up everything a visual test needs before navigating:
 *
 * - Freeze the page clock for deterministic elapsed-time rendering.
 * - Stub `EventSource` so the SSE "Live" indicator turns on without a backend.
 * - Intercept every `/api/**` and run-scoped `/v1/**` request with canned
 *   responses derived from the mocks above, parametrised by `armed` / `paused`.
 *
 * Call this *before* `page.goto(...)`.
 */
export async function setupVisualTest(page: Page, opts: SetupOptions = {}): Promise<void> {
  const { armed = true, paused = true, selectedExchangeId, exchanges = mockExchanges } = opts;

  await page.clock.install({ time: FROZEN_NOW });

  await page.addInitScript(
    ({ selectedId, uiStoreKey }: { selectedId?: string; uiStoreKey: string }) => {
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
      // first render; zustand's persist middleware reads this key at hydrate.
      if (selectedId) {
        localStorage.setItem(uiStoreKey, JSON.stringify({ state: { selectedId }, version: 0 }));
      }
    },
    { selectedId: selectedExchangeId, uiStoreKey: FRONTEND_STORAGE_KEYS.uiStore },
  );

  const fulfillExchangeDetail = async (route: Route, encodedId: string) => {
    const id = decodeURIComponent(encodedId);
    const detail = mockExchangeDetails[id];
    if (detail) {
      return route.fulfill({ json: detail });
    }
    return route.fulfill({ status: 404, json: { error: "not found" } });
  };

  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const p = url.pathname;

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
    if (p === "/api/meta") {
      return route.fulfill({ json: MOCK_META });
    }

    // Unknown route; return empty JSON so nothing throws.
    return route.fulfill({ json: {} });
  });

  await page.route("**/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const p = url.pathname;
    const runPrefix = `/v1/runs/${mockVisualRunId}`;

    if (p === `${runPrefix}/exchanges`) {
      return route.fulfill({ json: exchanges });
    }

    const turnContentMatch = p.match(/^\/v1\/runs\/([^/]+)\/exchanges\/([^/]+)\/turn-content$/);
    if (turnContentMatch) {
      const [, runId] = turnContentMatch;
      if (runId !== mockVisualRunId) {
        return route.fulfill({ status: 404, json: { error: "not found" } });
      }
      return route.fulfill({
        json: {
          user_text: "fixture user prompt",
          response_text: "fixture assistant response",
          stop_reason: "end_turn",
        },
      });
    }

    const detailMatch = p.match(/^\/v1\/runs\/([^/]+)\/exchanges\/([^/]+)$/);
    if (detailMatch) {
      const [, runId, encodedId] = detailMatch;
      if (runId !== mockVisualRunId) {
        return route.fulfill({ status: 404, json: { error: "not found" } });
      }
      if (encodedId === undefined) {
        return route.fulfill({ status: 404, json: { error: "not found" } });
      }
      return fulfillExchangeDetail(route, encodedId);
    }

    // Unknown route; return empty JSON so nothing throws.
    return route.fulfill({ json: {} });
  });
}
