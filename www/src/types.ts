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
  cache_read_input_tokens: number;
  text_chars: number;
  tool_calls: number;
}

export interface IndexEntry {
  id: string;
  ts: string;
  provider: string;
  model: string;
  path: string;
  req: ReqStats;
  pipeline: PipelineAudit | null;
  res: ResStats | null;
  mutated_manually: boolean;
}

export interface ExchangeDetail {
  entry: IndexEntry;
  request_ir: Record<string, unknown>;
  response_ir: Record<string, unknown> | null;
}

export type ActionType =
  | "strip_tools"
  | "strip_thinking"
  | "strip_system_part"
  | "truncate_system_part"
  | "truncate_tool_result"
  | "rewrite_tool_description";

export interface RuleScope {
  global: boolean;
  session_id: string | null;
  device_id: string | null;
  account_id: string | null;
  model: string | null;
}

export interface Rule {
  id: string;
  name: string;
  enabled: boolean;
  scope: RuleScope;
  action: ActionType;
  params: Record<string, unknown>;
  created_at: string;
  applied_count: number;
}

export interface CreateRuleBody {
  name: string;
  scope: RuleScope;
  action: ActionType;
  params: Record<string, unknown>;
  enabled?: boolean;
}

export interface PatchRuleBody {
  name?: string;
  enabled?: boolean;
  params?: Record<string, unknown>;
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

// ── Pipeline audit ────────────────────────────────────────────────

export interface RuleAuditEntry {
  id: string;
  name: string;
  action: string;
  removed: Record<string, number>;
}
export interface PipelineAudit {
  rules_applied: RuleAuditEntry[];
  chars_before: number;
  chars_after: number;
}

// ── Breakpoint ────────────────────────────────────────────────────

export interface PausedFlow {
  flow_id: string;
  ir: InternalRequest;
  audit: PipelineAudit | null;
  paused_at_ms: number;
}

export interface BreakpointStatusDetail {
  mode: "off" | "armed_once";
  paused_flows: Array<{ flow_id: string; paused_at_ms: number }>;
}
