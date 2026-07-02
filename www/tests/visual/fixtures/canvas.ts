import type { Page, Route } from "@playwright/test";
import { FRONTEND_STORAGE_KEYS } from "../../../src/stores/persistence";
import { mockExchangeDetails } from "./details";
import { mockExchanges, mockVisualRunId } from "./exchanges";

/**
 * Canvas-route test setup, shared by the keybinding e2e specs and the canvas
 * visual specs: canned /api + /v1 responses (reusing the visual exchange
 * fixtures) plus a localStorage seed that opens a provider-exchange pane on
 * the "direct-local" canvas without any backend.
 */

export async function setupCanvasApis(page: Page): Promise<void> {
  await page.route((url) => url.pathname.startsWith("/api/"), fulfillCanvasApiRoute);
  await page.route((url) => url.pathname.startsWith("/v1/"), fulfillCanvasV1Route);
}

async function fulfillCanvasApiRoute(route: Route): Promise<void> {
  const path = new URL(route.request().url()).pathname;

  if (path === "/api/meta") {
    return route.fulfill({
      json: {
        cwd: "/Users/alphab/Dev/LLM/DEV/helioy/transport-matters",
        workspace_id: "helioy/transport-matters",
        run_id: mockVisualRunId,
      },
    });
  }

  if (path === "/api/breakpoint/status") {
    return route.fulfill({ json: { mode: "off", paused_flows: [] } });
  }

  return route.fulfill({ json: {} });
}

async function fulfillCanvasV1Route(route: Route): Promise<void> {
  const path = new URL(route.request().url()).pathname;

  if (path === "/v1/runtime-templates") {
    return route.fulfill({
      json: {
        items: [
          {
            name: "research",
            vendors: ["anthropic"],
            required_capabilities: [],
            recommended_model: { default: { harness: "claude", vendor: "anthropic" } },
          },
        ],
      },
    });
  }

  if (path === `/v1/runs/${mockVisualRunId}/exchanges`) {
    return route.fulfill({ json: mockExchanges });
  }

  const detailMatch = path.match(/^\/v1\/runs\/([^/]+)\/exchanges\/([^/]+)$/);
  if (detailMatch) {
    const [, runId, encodedId] = detailMatch;
    const detail = mockExchangeDetails[decodeURIComponent(encodedId ?? "")];
    if (runId === mockVisualRunId && detail) return route.fulfill({ json: detail });
    return route.fulfill({ status: 404, json: { error: "not found" } });
  }

  return route.fulfill({ json: {} });
}

export interface SeedCanvasExchangePaneOptions {
  exchangeId?: string;
  /** Seed the exchange pane as the expanded (hero) pane so it fills the view. */
  expanded?: boolean;
}

export async function seedCanvasExchangePane(
  page: Page,
  { exchangeId = mockExchanges[0].id, expanded = false }: SeedCanvasExchangePaneOptions = {},
): Promise<void> {
  await page.addInitScript(
    ({
      storageKey,
      runId,
      exchangeId,
      expanded,
    }: {
      storageKey: string;
      runId: string;
      exchangeId: string;
      expanded: boolean;
    }) => {
      const exchangePaneId = `exchange:${runId}:${exchangeId}`;
      localStorage.setItem(
        storageKey,
        JSON.stringify({
          version: 1,
          state: {
            contentRefs: {
              "session-picker": { kind: "session-picker", owner: "local" },
              [exchangePaneId]: {
                kind: "provider-exchange",
                owner: "local",
                sessionId: "visual-session",
                runId,
                exchangeId,
                initialView: "inspect",
              },
            },
            paneRects: {
              "session-picker": { x: 32, y: 32, width: 380, height: 520 },
              [exchangePaneId]: { x: 444, y: 32, width: 760, height: 700 },
            },
            order: ["session-picker", exchangePaneId],
            docked: [],
            fitToContent: true,
            expandedPaneId: expanded ? exchangePaneId : null,
          },
        }),
      );
    },
    {
      // Slice 6 namespaces the canvas cache by canvasId; /canvas with no launch
      // params resolves to the "direct-local" canvas, so seed THAT key directly
      // (the bare legacy key is only the one-time import source).
      storageKey: `${FRONTEND_STORAGE_KEYS.canvasStore}:direct-local`,
      runId: mockVisualRunId,
      exchangeId,
      expanded,
    },
  );
}
