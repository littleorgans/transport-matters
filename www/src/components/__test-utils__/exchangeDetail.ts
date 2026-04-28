import type {
  CodexTurnListSummary,
  ExchangeDetail,
  IndexEntry,
  ReqStats,
  ResStats,
} from "../../types";

type DetailOverrides = Partial<Omit<ExchangeDetail, "entry">> & { entry?: Partial<IndexEntry> };

export const detailResStats: ResStats = {
  stop_reason: "end_turn",
  input_tokens: 10,
  output_tokens: 5,
  cache_creation_input_tokens: 0,
  cache_read_input_tokens: 0,
  text_chars: 20,
  tool_calls: 0,
};

export const openCodexTurnListSummary: CodexTurnListSummary = {
  turn_index: 4,
  message_range_start: 0,
  message_range_end: 0,
  status: "open",
  terminal_cause: null,
  stop_reason: null,
  text_chars: 12,
  tool_calls: 0,
};

const detailReqStats: ReqStats = {
  system_parts: 0,
  system_chars: 0,
  tools_count: 0,
  tools_chars: 0,
  messages_count: 1,
  messages_chars: 10,
  total_chars: 10,
};

export function makeExchangeDetail(overrides: DetailOverrides = {}): ExchangeDetail {
  const { entry: entryOverrides, ...detailOverrides } = overrides;
  const provider = entryOverrides?.provider ?? "anthropic";
  const model =
    entryOverrides?.model ?? (provider === "codex" ? "codex/gpt-5-codex" : "anthropic/claude-3");
  const entry: IndexEntry = {
    id: "exchange-001",
    ts: new Date("2026-01-01T12:00:00Z").toISOString(),
    provider,
    model,
    path: "exchanges/test/",
    req: detailReqStats,
    pipeline: null,
    res: null,
    mutated_manually: false,
    ...entryOverrides,
  };

  return {
    entry,
    request_ir: { model, messages: [] },
    request_curated_ir: null,
    request_audit: null,
    response_ir: null,
    transport: null,
    events: null,
    turn: null,
    transport_diagnostics: [],
    ...detailOverrides,
  };
}
