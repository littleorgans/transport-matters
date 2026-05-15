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

export type HarnessProxyMode = "reverse" | "explicit";
export type HarnessTrustRequirement = "none" | "codex_ca_certificate";
export type HarnessShellEnvironmentPolicy =
  | "sanitized_base_url"
  | "sanitized_proxy_with_shell_excludes";
export type HarnessPassThroughPolicy = "verbatim_after_separator";

export interface HarnessCapabilities {
  startup_probe: boolean;
  disposable_probe: boolean;
  overlay_before_work: boolean;
  tool_schema_overlay: boolean;
  provider_extras_controls: boolean;
  replay: boolean;
  fork: boolean;
  transport_diagnostics: boolean;
  codex_turn_telemetry: boolean;
  websocket_artifacts: boolean;
  http_fallback_artifacts: boolean;
}

export interface HarnessDescriptor {
  id: string;
  display_name: string;
  command_name: string;
  subcommand_id: string;
  binary_option: string;
  disable_flag: string;
  proxy_mode: HarnessProxyMode;
  trust_requirement: HarnessTrustRequirement;
  shell_environment_policy: HarnessShellEnvironmentPolicy;
  pass_through_policy: HarnessPassThroughPolicy;
  capabilities: HarnessCapabilities;
}

export interface CodexTurnListSummary {
  turn_index: number;
  message_range_start: number;
  message_range_end: number;
  status: CodexTurnStatus;
  terminal_cause: CodexTerminalCause | null;
  stop_reason: string | null;
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
  /** Original request IR as received from the client, pre-pipeline and pre-edit. */
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

export type CodexDerivedArtifactsStatus =
  | "not_applicable"
  | "supported"
  | "missing"
  | "migration_required"
  | "inconsistent";

export type CodexDerivedArtifactsRepairAction = "none" | "repaired" | "migrated";

export interface CodexDerivedArtifactsDiagnostic {
  severity: "info" | "warning" | "error";
  code: string;
  summary: string;
  detail?: string | null;
}

export interface CodexDerivedArtifactsRepairState {
  action: CodexDerivedArtifactsRepairAction;
  status_before: CodexDerivedArtifactsStatus;
}

export interface CodexDerivedArtifactsState {
  status: CodexDerivedArtifactsStatus;
  diagnostics: CodexDerivedArtifactsDiagnostic[];
  repair: CodexDerivedArtifactsRepairState | null;
}

export type CodexEventSource = "client" | "server" | "proxy" | "operator";

export type CodexSemanticEventKind =
  | "turn_started"
  | "request_curated"
  | "breakpoint_paused"
  | "breakpoint_released"
  | "assistant_item_completed"
  | "tool_call_completed"
  | "tool_output_submitted"
  | "response_completed"
  | "response_failed"
  | "turn_finalized";

export type CodexTurnStatus = "open" | "completed" | "failed" | "interrupted";

export type CodexTerminalCause = "response_completed" | "response_failed" | "websocket_close";

export interface CodexTransportRef {
  message_index: number;
}

export interface CodexOpenAssistantItem {
  text: string;
}

export interface CodexOpenToolCall {
  arguments: string;
}

export interface CodexDerivationCursor {
  next_message_index: number;
  next_seq: number;
  open_assistant_items: Record<string, CodexOpenAssistantItem>;
  open_tool_calls: Record<string, CodexOpenToolCall>;
  terminal_seen: boolean;
}

export interface CodexBreakpointEventData {
  flow_id?: string;
}

export interface CodexAssistantItemCompletedData {
  item_id?: string;
  item_type: string;
  phase?: string;
  role?: string;
  text_chars: number;
}

export interface CodexToolCallCompletedData {
  arguments_chars: number;
  call_id?: string;
  item_id?: string;
  item_type: string;
  tool_name?: string;
}

export interface CodexToolOutputSubmittedData {
  call_id?: string;
  input_index: number;
  item_type: string;
  output_chars: number;
}

export interface CodexResponseTerminalData {
  response_id?: string;
  response_status?: string;
  stop_reason: string;
}

export interface CodexTurnFinalizedData {
  close_code?: number;
  status: CodexTurnStatus;
  stop_reason: string;
  terminal_cause: CodexTerminalCause;
  text_chars: number;
  tool_calls: number;
}

export type CodexSemanticEventDataByKind = {
  turn_started: Record<string, never>;
  request_curated: Record<string, unknown>;
  breakpoint_paused: CodexBreakpointEventData;
  breakpoint_released: CodexBreakpointEventData;
  assistant_item_completed: CodexAssistantItemCompletedData;
  tool_call_completed: CodexToolCallCompletedData;
  tool_output_submitted: CodexToolOutputSubmittedData;
  response_completed: CodexResponseTerminalData;
  response_failed: CodexResponseTerminalData;
  turn_finalized: CodexTurnFinalizedData;
};

interface CodexSemanticEventBase<Kind extends CodexSemanticEventKind> {
  event_id: string;
  exchange_id: string;
  session_id: string;
  turn_id: string;
  seq: number;
  ts: string;
  source: CodexEventSource;
  kind: Kind;
  transport_ref: CodexTransportRef | null;
  data: CodexSemanticEventDataByKind[Kind];
  derivation_version: number;
}

export type CodexSemanticEvent = {
  [Kind in CodexSemanticEventKind]: CodexSemanticEventBase<Kind>;
}[CodexSemanticEventKind];

export interface CodexTurnSummary {
  turn_id: string;
  exchange_id: string;
  session_id: string;
  turn_index: number;
  request_message_index: number;
  terminal_message_index: number | null;
  terminal_cause: CodexTerminalCause | null;
  message_range_start: number;
  message_range_end: number;
  model: string;
  status: CodexTurnStatus;
  stop_reason: string | null;
  text_chars: number;
  tool_calls: number;
  started_at: string;
  ended_at: string | null;
  derivation_version: number;
  cursor: CodexDerivationCursor | null;
}

// ── Overrides ─────────────────────────────────────────────────────

export type OverrideKind =
  | "tool_toggle"
  | "tool_description"
  | "system_part_toggle"
  | "system_part_text"
  | "message_block_toggle"
  | "message_text"
  | "truncate_tool_result"
  | "sampling_set"
  | "provider_extras_set";

export interface Override {
  kind: OverrideKind;
  target: string;
  value: string | boolean | number | null;
}

export interface OverrideScope {
  run_id?: string | null;
  track_id?: string | null;
}

export interface OverrideAuditEntry {
  kind: string;
  target: string;
  applied: boolean;
  chars_delta: number;
  /**
   * Populated for text-bearing kinds (``system_part_text``,
   * ``tool_description``, ``message_text``, ``truncate_tool_result``) when
   * ``applied`` is true. Toggle and scalar kinds leave this null. The
   * Inspect tab uses it to synthesise read-only overrides against the
   * ORIGINAL IR without replaying the server's pop-cascade when block
   * toggles shift later targets.
   */
  curated_value: string | null;
}

export interface OverrideAudit {
  entries: OverrideAuditEntry[];
  chars_before: number;
  chars_after: number;
  system_chars_before: number;
  system_chars_after: number;
  tools_chars_before: number;
  tools_chars_after: number;
  messages_chars_before: number;
  messages_chars_after: number;
}

export interface TransportHeader {
  name: string;
  value: string;
}

export interface TransportUpgradeArtifacts {
  scheme: string;
  host: string;
  path: string;
  request_headers: TransportHeader[];
  response_status_code: number | null;
  response_headers: TransportHeader[];
}

export interface TransportHttpRequestArtifacts {
  method: string | null;
  scheme: string;
  host: string;
  path: string;
  headers: TransportHeader[];
}

export interface TransportHttpResponseArtifacts {
  status_code: number | null;
  headers: TransportHeader[];
}

export interface TransportCloseArtifacts {
  ts?: string | null;
  close_code: number | null;
  close_reason: string | null;
  closed_by_client: boolean | null;
  initial_client_frame_captured: boolean;
  client_message_count: number;
  server_message_count: number;
}

export interface TransportMessageArtifact {
  ts?: string | null;
  direction: "client" | "server";
  is_text: boolean;
  size_bytes: number;
  dropped: boolean;
  event_type: string | null;
  payload_text: string | null;
  payload_json: Record<string, unknown> | unknown[] | null;
  payload_base64: string | null;
}

interface TransportArtifactsBase {
  provider: string;
  messages: TransportMessageArtifact[];
}

export interface TransportWebSocketArtifacts extends TransportArtifactsBase {
  protocol: "websocket";
  upgrade: TransportUpgradeArtifacts;
  close: TransportCloseArtifacts | null;
}

export interface TransportHttpArtifacts extends TransportArtifactsBase {
  protocol: "http";
  request: TransportHttpRequestArtifacts | null;
  response: TransportHttpResponseArtifacts | null;
}

export type TransportArtifacts = TransportWebSocketArtifacts | TransportHttpArtifacts;

export interface TransportDiagnostic {
  severity: "info" | "warning" | "error";
  code: string;
  summary: string;
  detail: string | null;
  operator_checks: string[];
}

// ── IR content blocks ─────────────────────────────────────────────

export interface TextBlock {
  type: "text";
  text: string;
}
export interface ToolUseBlock {
  type: "tool_use";
  id: string;
  name: string;
  input: Record<string, unknown>;
}
export interface ToolResultBlock {
  type: "tool_result";
  tool_use_id: string;
  content: Array<TextBlock | ImageBlock>;
  is_error: boolean;
}
export interface ThinkingBlock {
  type: "thinking";
  text: string;
  provider_data?: Record<string, unknown>;
}
export interface ImageBlock {
  type: "image";
  source: Record<string, unknown>;
}
export interface UnknownBlock {
  type: "unknown";
  raw: Record<string, unknown>;
}
export type ContentBlock =
  | TextBlock
  | ToolUseBlock
  | ToolResultBlock
  | ThinkingBlock
  | ImageBlock
  | UnknownBlock;

export interface Message {
  role: "user" | "assistant";
  content: ContentBlock[];
}
export interface SystemPart {
  type: "text";
  text: string;
  cache_hint?: Record<string, unknown>;
  provider_data?: Record<string, unknown>;
}
export interface ToolDef {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  provider_data?: Record<string, unknown>;
}
export interface SamplingParams {
  max_tokens: number;
  temperature: number | null;
  top_p: number | null;
  top_k: number | null;
  stop_sequences: string[];
}
export interface RequestMetadata {
  session_id: string | null;
  device_id: string | null;
  account_id: string | null;
  provider_metadata: Record<string, unknown>;
}

export interface InternalRequest {
  model: string;
  provider: string;
  system: SystemPart[];
  tools: ToolDef[];
  messages: Message[];
  sampling: SamplingParams;
  metadata: RequestMetadata;
  stream: boolean;
  provider_extras: Record<string, unknown>;
}

// ── Response IR ──────────────────────────────────────────────────

export interface UsageStats {
  input_tokens: number;
  output_tokens: number;
  cache_creation_input_tokens: number;
  cache_read_input_tokens: number;
}

export interface InternalResponse {
  id: string;
  model: string;
  provider: string;
  stop_reason: string | null;
  usage: UsageStats;
  content: ContentBlock[];
  provider_extras: Record<string, unknown>;
}

// ── Pipeline stats (stored with exchanges) ───────────────────────

export interface PipelineStats {
  overrides_applied: OverrideAuditEntry[];
  chars_before: number;
  chars_after: number;
  // Authoritative counts from /v1/messages/count_tokens. null means the
  // endpoint failed or the row predates counter integration; the UI should
  // render an em dash rather than fall back to a chars/4 estimate.
  tokens_before: number | null;
  tokens_after: number | null;
}

// ── Breakpoint ────────────────────────────────────────────────────

export interface PausedFlow {
  flow_id: string;
  transport: "http" | "websocket";
  provisional_exchange_id?: string | null;
  run_id?: string | null;
  track_id?: string | null;
  parent_track_id?: string | null;
  track_display_name?: string | null;
  track_role?: "parent" | "subagent" | null;
  spawn_anchor?: SpawnAnchor | null;
  ir: InternalRequest;
  original_tools: ToolDef[];
  original_system: SystemPart[];
  original_messages: Message[];
  /**
   * Pristine sampling/provider_extras as the client sent them, pre-override.
   * The editor uses these as the "revert to" reference when a user clears
   * a sampling_set or provider_extras_set override — ir.sampling already
   * reflects any active overrides layered on top.
   */
  original_sampling: SamplingParams;
  original_provider_extras: Record<string, unknown>;
  audit: OverrideAudit | null;
  paused_at_ms: number;
  /**
   * count_tokens result for the IR currently staged to be forwarded.
   * Null until the count lands (fire-and-forget on pause) or when the
   * call fails — the UI renders an em dash in that case.
   */
  tokens_before: number | null;
}

export interface BreakpointStatusDetail {
  mode: "off" | "armed_once";
  paused_flows: Array<{ flow_id: string; paused_at_ms: number }>;
}
