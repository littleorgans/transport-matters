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
