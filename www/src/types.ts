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
