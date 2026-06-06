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
    session_id: patch.session_id ?? "session-1",
    provider: patch.provider ?? "anthropic",
    cli: patch.cli ?? "claude",
    run_id: patch.run_id ?? "run-1",
    cwd: patch.cwd ?? "/tmp/project",
    workspace_slug: patch.workspace_slug ?? "project",
    workspace_hash: patch.workspace_hash ?? "hash-1",
    native_session_id: patch.native_session_id ?? "native-1",
    minted: patch.minted ?? false,
    source_descriptor: patch.source_descriptor ?? null,
    home_dir: patch.home_dir ?? null,
    owner: patch.owner ?? "local",
    status: patch.status ?? "active",
    title: patch.title ?? "Project agent",
    parent_session_id: patch.parent_session_id ?? null,
    forked_at_seq: patch.forked_at_seq ?? null,
    started_at: patch.started_at ?? "2026-06-06T17:00:00Z",
    created_at: patch.created_at ?? "2026-06-06T17:00:00Z",
    updated_at: patch.updated_at ?? "2026-06-06T17:01:00Z",
  };
}

export function makeSessionEvent(
  patch: Partial<import("./api/sessionEvents").SessionEventView> = {},
): import("./api/sessionEvents").SessionEventView {
  return {
    session_id: patch.session_id ?? "session-1",
    seq: patch.seq ?? 0,
    kind: patch.kind ?? "turn",
    native_turn_id: patch.native_turn_id ?? "turn-1",
    parent_native_id: patch.parent_native_id ?? null,
    parent_seq: patch.parent_seq ?? null,
    run_id: patch.run_id ?? "run-1",
    provider: patch.provider ?? "anthropic",
    cli: patch.cli ?? "claude",
    role: patch.role ?? "assistant",
    is_sidechain: patch.is_sidechain ?? false,
    ts: patch.ts ?? "2026-06-06T17:00:00Z",
    model: patch.model ?? "claude-sonnet",
    ir: Object.hasOwn(patch, "ir")
      ? (patch.ir ?? null)
      : {
          parts: [{ type: "text", text: "hello transcript" }],
        },
    source_path: patch.source_path ?? "/tmp/transcript.jsonl",
    source_line: patch.source_line ?? 1,
    search_text: patch.search_text ?? "hello transcript",
    created_at: patch.created_at ?? "2026-06-06T17:00:00Z",
  };
}
