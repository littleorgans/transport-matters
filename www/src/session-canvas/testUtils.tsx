import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { type ApiTransport, resetApiTransport, setApiTransport } from "../api";
import type { SessionSummary } from "./api/sessionClient";

export function renderWithQuery(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

export function installMockTransport(
  handler: (path: string) => Response | Promise<Response>,
): void {
  const transport: ApiTransport = {
    request(path) {
      return Promise.resolve(handler(path));
    },
  };
  setApiTransport(transport);
}

export function restoreTransport(): void {
  resetApiTransport();
}

export function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}

export function makeSessionSummary(patch: Partial<SessionSummary> = {}): SessionSummary {
  return {
    sessionId: patch.sessionId ?? "session-1",
    workspaceId: patch.workspaceId ?? "project/hash-1",
    title: patch.title ?? "Project agent",
    status: patch.status ?? "active",
    provider: patch.provider ?? "anthropic",
    harness: patch.harness ?? "claude",
    createdAt: patch.createdAt ?? "2026-06-06T17:00:00Z",
    lastActivityAt: patch.lastActivityAt ?? "2026-06-06T17:01:00Z",
    purpose: patch.purpose ?? "user",
    visibility: patch.visibility ?? "user_visible",
    lineage: patch.lineage ?? {
      parentSessionId: null,
      forkedAtSeq: null,
      forkedAtTurn: null,
    },
    turnCount: patch.turnCount ?? 1,
    inheritedTurnCount: patch.inheritedTurnCount ?? 0,
    lastMessagePreview: patch.lastMessagePreview ?? "hello transcript",
  };
}

export function makeSessionEvent(
  patch: Partial<import("./api/sessionEvents").SessionEventView> = {},
): import("./api/sessionEvents").SessionEventView {
  return {
    seq: patch.seq ?? 0,
    turnIndex: patch.turnIndex ?? 1,
    kind: patch.kind ?? "turn",
    role: patch.role ?? "assistant",
    ts: patch.ts ?? "2026-06-06T17:00:00Z",
    body: patch.body ?? {
      kind: "assistant",
      parts: [{ type: "text", text: "hello transcript" }],
    },
    nativePayload:
      patch.nativePayload === null
        ? null
        : (patch.nativePayload ?? { type: "message", text: "hello transcript" }),
    resourceRefs: patch.resourceRefs ?? [],
  };
}
