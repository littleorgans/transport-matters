import type {
  CodexDerivedArtifactsState,
  CodexSemanticEvent,
  CodexTurnListSummary,
  CodexTurnSummary,
} from "./codex";
import type { InternalRequest, Message, SamplingParams, SystemPart, ToolDef } from "./ir";
import type { OverrideAudit, OverrideAuditEntry } from "./overrides";
import type { TransportArtifacts, TransportDiagnostic } from "./transport";

export interface ReqStats {
  system_parts: number;
  system_chars: number;
  tools_count: number;
  tools_chars: number;
  messages_count: number;
  messages_chars: number;
  total_chars: number;
}

export interface ResStats {
  stop_reason: string | null;
  input_tokens: number;
  output_tokens: number;
  cache_creation_input_tokens: number;
  cache_read_input_tokens: number;
  text_chars: number;
  tool_calls: number;
}

export type TrackRole = "parent" | "subagent";
export type TrackStatus = "pending" | "live" | "closed";

export interface SpawnAnchor {
  track_spawn_exchange_id: string | null;
  track_spawn_tool_use_id: string | null;
  track_spawn_order: number | null;
}

export interface ExchangeTrackStub {
  track_id: string;
  parent_track_id: string | null;
  track_display_name?: string | null;
  track_role?: TrackRole | null;
  status?: TrackStatus | null;
  spawn_anchor?: SpawnAnchor | null;
}

export interface IndexEntry {
  id: string;
  run_id?: string | null;
  track_id?: string | null;
  parent_track_id?: string | null;
  track_display_name?: string | null;
  track_role?: TrackRole | null;
  spawn_anchor?: SpawnAnchor | null;
  ts: string;
  provider: string;
  model: string;
  path: string;
  req: ReqStats;
  pipeline: PipelineStats | null;
  res: ResStats | null;
  codex_turn?: CodexTurnListSummary | null;
  mutated_manually: boolean;
}

export interface TurnContent {
  user_text: string | null;
  response_text: string | null;
  stop_reason: string | null;
}

export interface ExchangeTrack {
  track_id: string;
  parent_track_id: string | null;
  track_display_name: string | null;
  track_role: TrackRole;
  status: TrackStatus;
  // Runtime tracks keep wire spawn_anchor fields flat. The tree builder adopts
  // each non null nested anchor field as the latest concrete value for display.
  track_spawn_exchange_id: string | null;
  track_spawn_tool_use_id: string | null;
  track_spawn_order: number | null;
  exchanges: IndexEntry[];
  children: ExchangeTrack[];
}

export interface ExchangeDetail {
  entry: IndexEntry;
  /** Original request IR as received from the client, before pipeline and edit. */
  request_ir: Record<string, unknown>;
  /**
   * Final request IR actually sent to the provider: pipeline output merged
   * with any user edits made at a breakpoint. Null when neither the pipeline
   * nor the user mutated the original request.
   */
  request_curated_ir: Record<string, unknown> | null;
  request_audit: OverrideAudit | null;
  response_ir: Record<string, unknown> | null;
  transport: TransportArtifacts | null;
  events?: CodexSemanticEvent[] | null;
  turn?: CodexTurnSummary | null;
  codex_derived_artifacts?: CodexDerivedArtifactsState | null;
  transport_diagnostics: TransportDiagnostic[];
}

export interface PipelineStats {
  overrides_applied: OverrideAuditEntry[];
  chars_before: number;
  chars_after: number;
  // Authoritative counts from /v1/messages/count_tokens. null means the
  // endpoint failed or the row predates counter integration; the UI should
  // render a placeholder rather than fall back to a chars/4 estimate.
  tokens_before: number | null;
  tokens_after: number | null;
}

/**
 * An exchange paused in flight, as emitted on the exchange stream ("paused"
 * event) and by `GET /api/breakpoint/paused/{flow_id}`. Wire-level exchange
 * lifecycle data: the core stream primitive parses and constructs it, so it
 * lives with the exchange types rather than the breakpoint control surface.
 */
export interface PausedFlow {
  flow_id: string;
  transport: "http" | "websocket";
  provisional_exchange_id?: string | null;
  run_id?: string | null;
  track_id?: string | null;
  parent_track_id?: string | null;
  track_display_name?: string | null;
  track_role?: TrackRole | null;
  spawn_anchor?: SpawnAnchor | null;
  ir: InternalRequest;
  original_tools: ToolDef[];
  original_system: SystemPart[];
  original_messages: Message[];
  /**
   * Pristine sampling/provider_extras as the client sent them before override.
   * The editor uses these as the revert reference when a user clears a
   * sampling_set or provider_extras_set override.
   */
  original_sampling: SamplingParams;
  original_provider_extras: Record<string, unknown>;
  audit: OverrideAudit | null;
  paused_at_ms: number;
  /**
   * count_tokens result for the IR currently staged to be forwarded. Null
   * until the count lands or when the call fails.
   */
  tokens_before: number | null;
}
