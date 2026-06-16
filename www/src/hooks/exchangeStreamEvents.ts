import type { QueryClient } from "@tanstack/react-query";
import { MAX_ENTRIES } from "../api";
import { exchangeKey, exchangesKey, turnContentKey } from "../lib/queryKeys";
import { useUIStore } from "../stores/uiStore";
import type { CodexTurnListSummary, IndexEntry, PausedFlow, SpawnAnchor } from "../types";

export interface ExchangeStreamEventContext {
  runId: string;
  queryClient: QueryClient;
  setPausedFlow: (flow: PausedFlow | null) => void;
  clearPausedFlow: () => void;
  setSelectedId: (id: string | null) => void;
}

function isValidPausedEvent(data: Record<string, unknown>): data is {
  type: "paused";
  flow_id: string;
  transport?: PausedFlow["transport"];
  provisional_exchange_id?: string | null;
  run_id?: string | null;
  track_id?: string | null;
  parent_track_id?: string | null;
  track_display_name?: string | null;
  track_role?: PausedFlow["track_role"];
  spawn_anchor?: SpawnAnchor | null;
  ir: PausedFlow["ir"];
  original_tools?: PausedFlow["original_tools"];
  original_system?: PausedFlow["original_system"];
  original_messages?: PausedFlow["original_messages"];
  original_sampling?: PausedFlow["original_sampling"];
  original_provider_extras?: PausedFlow["original_provider_extras"];
  audit?: PausedFlow["audit"];
  paused_at_ms: number;
  tokens_before?: number | null;
} {
  return (
    typeof data.flow_id === "string" &&
    typeof data.paused_at_ms === "number" &&
    data.ir != null &&
    typeof data.ir === "object"
  );
}

function isValidPausedTokensEvent(data: Record<string, unknown>): data is {
  type: "paused_tokens";
  flow_id: string;
  tokens_before: number | null;
} {
  return (
    typeof data.flow_id === "string" &&
    (typeof data.tokens_before === "number" || data.tokens_before === null)
  );
}

function isValidExchangeEvent(data: Record<string, unknown>): data is {
  type: "exchange";
  id: string;
  run_id?: string | null;
  ts: string;
  provider: string;
  model: string;
  req: IndexEntry["req"];
  pipeline?: IndexEntry["pipeline"];
  res?: IndexEntry["res"];
  codex_turn?: IndexEntry["codex_turn"];
  mutated_manually?: boolean;
  track_id?: string | null;
  parent_track_id?: string | null;
  track_display_name?: string | null;
  track_role?: IndexEntry["track_role"];
  spawn_anchor?: SpawnAnchor | null;
  flow_id?: string;
} {
  return (
    typeof data.id === "string" &&
    typeof data.ts === "string" &&
    typeof data.provider === "string" &&
    typeof data.model === "string" &&
    data.req != null &&
    typeof data.req === "object"
  );
}

function parseCodexTurnSummary(value: unknown): CodexTurnListSummary | null {
  if (value == null || typeof value !== "object") return null;
  const candidate = value as Record<string, unknown>;
  if (
    typeof candidate.turn_index !== "number" ||
    typeof candidate.message_range_start !== "number" ||
    typeof candidate.message_range_end !== "number" ||
    (candidate.status !== "open" &&
      candidate.status !== "completed" &&
      candidate.status !== "failed" &&
      candidate.status !== "interrupted") ||
    (candidate.terminal_cause !== null &&
      candidate.terminal_cause !== undefined &&
      candidate.terminal_cause !== "response_completed" &&
      candidate.terminal_cause !== "response_failed" &&
      candidate.terminal_cause !== "websocket_close") ||
    (candidate.stop_reason !== null &&
      candidate.stop_reason !== undefined &&
      typeof candidate.stop_reason !== "string") ||
    typeof candidate.text_chars !== "number" ||
    typeof candidate.tool_calls !== "number"
  ) {
    return null;
  }
  return {
    turn_index: candidate.turn_index,
    message_range_start: candidate.message_range_start,
    message_range_end: candidate.message_range_end,
    status: candidate.status,
    terminal_cause: candidate.terminal_cause ?? null,
    stop_reason: candidate.stop_reason ?? null,
    text_chars: candidate.text_chars,
    tool_calls: candidate.tool_calls,
  };
}

function isValidExchangeDeletedEvent(data: Record<string, unknown>): data is {
  type: "exchange_deleted";
  id: string;
  run_id?: string | null;
  flow_id?: string;
} {
  return typeof data.id === "string";
}

function parseTrackRole(value: unknown): IndexEntry["track_role"] {
  return value === "parent" || value === "subagent" ? value : null;
}

function parseSpawnAnchor(value: unknown): SpawnAnchor | null {
  if (value == null || typeof value !== "object") return null;
  const candidate = value as Record<string, unknown>;
  return {
    track_spawn_exchange_id:
      typeof candidate.track_spawn_exchange_id === "string"
        ? candidate.track_spawn_exchange_id
        : null,
    track_spawn_tool_use_id:
      typeof candidate.track_spawn_tool_use_id === "string"
        ? candidate.track_spawn_tool_use_id
        : null,
    track_spawn_order:
      typeof candidate.track_spawn_order === "number" ? candidate.track_spawn_order : null,
  };
}

function bumpForwardingActivity(data: Record<string, unknown>) {
  const flowId = typeof data.flow_id === "string" ? data.flow_id : null;
  if (flowId && flowId === useUIStore.getState().forwardingFlowId) {
    useUIStore.getState().bumpForwardingActivity();
  }
}

function applyPausedEvent(data: Record<string, unknown>, context: ExchangeStreamEventContext) {
  if (!isValidPausedEvent(data)) return;
  context.setSelectedId(null);
  context.setPausedFlow({
    flow_id: data.flow_id,
    transport: data.transport === "websocket" ? "websocket" : "http",
    provisional_exchange_id:
      typeof data.provisional_exchange_id === "string" ? data.provisional_exchange_id : null,
    run_id: typeof data.run_id === "string" ? data.run_id : null,
    track_id: typeof data.track_id === "string" ? data.track_id : null,
    parent_track_id: typeof data.parent_track_id === "string" ? data.parent_track_id : null,
    track_display_name:
      typeof data.track_display_name === "string" ? data.track_display_name : null,
    track_role: parseTrackRole(data.track_role),
    spawn_anchor: parseSpawnAnchor(data.spawn_anchor),
    ir: data.ir,
    original_tools: data.original_tools ?? data.ir.tools,
    original_system: data.original_system ?? data.ir.system,
    original_messages: data.original_messages ?? data.ir.messages,
    original_sampling: data.original_sampling ?? data.ir.sampling,
    original_provider_extras: data.original_provider_extras ?? data.ir.provider_extras,
    audit: data.audit ?? null,
    paused_at_ms: data.paused_at_ms,
    tokens_before: data.tokens_before ?? null,
  });
}

function applyPausedTokensEvent(
  data: Record<string, unknown>,
  context: ExchangeStreamEventContext,
) {
  if (!isValidPausedTokensEvent(data)) return;
  const current = useUIStore.getState().pausedFlow;
  if (current && current.flow_id === data.flow_id) {
    context.setPausedFlow({ ...current, tokens_before: data.tokens_before });
  }
}

function buildExchangeEntry(data: {
  id: string;
  run_id?: string | null;
  track_id?: string | null;
  parent_track_id?: string | null;
  track_display_name?: string | null;
  track_role?: IndexEntry["track_role"];
  spawn_anchor?: SpawnAnchor | null;
  ts: string;
  provider: string;
  model: string;
  req: IndexEntry["req"];
  pipeline?: IndexEntry["pipeline"];
  res?: IndexEntry["res"];
  codex_turn?: IndexEntry["codex_turn"];
  mutated_manually?: boolean;
}): IndexEntry {
  return {
    id: data.id,
    run_id: data.run_id ?? null,
    track_id: data.track_id ?? data.run_id ?? null,
    parent_track_id: data.parent_track_id ?? null,
    track_display_name: data.track_display_name ?? null,
    track_role: parseTrackRole(data.track_role),
    spawn_anchor: parseSpawnAnchor(data.spawn_anchor),
    ts: data.ts,
    provider: data.provider,
    model: data.model,
    path: "",
    req: data.req,
    pipeline: data.pipeline ?? null,
    res: data.res ?? null,
    codex_turn: parseCodexTurnSummary(data.codex_turn),
    mutated_manually: data.mutated_manually ?? false,
  };
}

function mutateExchangeLists(
  queryClient: QueryClient,
  runId: string,
  transform: (entries: IndexEntry[]) => IndexEntry[],
) {
  queryClient.setQueryData<IndexEntry[]>(exchangesKey(runId, false), (prev = []) =>
    transform(prev),
  );
  queryClient.setQueriesData<IndexEntry[]>({ queryKey: exchangesKey(runId, true) }, (prev) =>
    prev ? transform(prev) : prev,
  );
}

function dropExchangeDetail(queryClient: QueryClient, runId: string, id: string) {
  queryClient.removeQueries({ queryKey: exchangeKey(runId, id), exact: true });
  queryClient.removeQueries({ queryKey: turnContentKey(runId, id), exact: true });
}

function upsertExchangeCache(queryClient: QueryClient, runId: string, entry: IndexEntry) {
  mutateExchangeLists(queryClient, runId, (prev) =>
    [entry, ...prev.filter((e) => e.id !== entry.id)].slice(0, MAX_ENTRIES),
  );
  void queryClient.invalidateQueries({ queryKey: exchangeKey(runId, entry.id) });
  void queryClient.invalidateQueries({ queryKey: turnContentKey(runId, entry.id) });
}

function applyExchangeEvent(data: Record<string, unknown>, context: ExchangeStreamEventContext) {
  if (!isValidExchangeEvent(data)) return;
  const entry = buildExchangeEntry(data);
  if (entry.run_id !== null && entry.run_id !== context.runId) return;
  upsertExchangeCache(context.queryClient, context.runId, entry);

  const { forwardingFlowId, pausedFlow } = useUIStore.getState();
  if (forwardingFlowId && data.flow_id === forwardingFlowId) {
    context.setSelectedId(entry.id);
    if (!pausedFlow || pausedFlow.flow_id === forwardingFlowId) {
      context.clearPausedFlow();
    } else {
      useUIStore.getState().setForwardingFlowId(null);
    }
  }
}

function applyExchangeDeletedEvent(
  data: Record<string, unknown>,
  context: ExchangeStreamEventContext,
) {
  if (!isValidExchangeDeletedEvent(data)) return;
  if (typeof data.run_id === "string" && data.run_id !== context.runId) return;
  mutateExchangeLists(context.queryClient, context.runId, (prev) =>
    prev.filter((entry) => entry.id !== data.id),
  );
  dropExchangeDetail(context.queryClient, context.runId, data.id);
  if (useUIStore.getState().selectedId === data.id) {
    context.setSelectedId(null);
  }
}

function applyParsedExchangeStreamEvent(
  data: Record<string, unknown>,
  context: ExchangeStreamEventContext,
) {
  bumpForwardingActivity(data);
  if (data.type === "paused") applyPausedEvent(data, context);
  if (data.type === "paused_tokens") applyPausedTokensEvent(data, context);
  if (data.type === "exchange") applyExchangeEvent(data, context);
  if (data.type === "exchange_deleted") applyExchangeDeletedEvent(data, context);
}

export function applyExchangeStreamEvent(
  message: string,
  context: ExchangeStreamEventContext,
): void {
  try {
    const data = JSON.parse(message) as Record<string, unknown>;
    applyParsedExchangeStreamEvent(data, context);
  } catch (error) {
    if (!(error instanceof SyntaxError)) console.error("SSE handler error:", error);
  }
}
