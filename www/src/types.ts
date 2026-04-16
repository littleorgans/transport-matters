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

export interface IndexEntry {
  id: string;
  run_id?: string | null;
  ts: string;
  provider: string;
  model: string;
  path: string;
  req: ReqStats;
  pipeline: PipelineStats | null;
  res: ResStats | null;
  mutated_manually: boolean;
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
  response_ir: Record<string, unknown> | null;
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
