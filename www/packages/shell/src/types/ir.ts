export interface TextBlock {
  type: "text";
  text: string;
  provider_data?: Record<string, unknown> | null;
}

export interface ToolUseBlock {
  type: "tool_use";
  id: string;
  name: string;
  input: Record<string, unknown>;
  provider_data?: Record<string, unknown> | null;
}

export interface ToolResultBlock {
  type: "tool_result";
  tool_use_id: string;
  content: Array<TextBlock | ImageBlock | UnknownBlock>;
  is_error: boolean;
  provider_data?: Record<string, unknown> | null;
}

export interface ThinkingBlock {
  type: "thinking";
  text: string;
  provider_data?: Record<string, unknown> | null;
}

export interface ImageBlock {
  type: "image";
  source: Record<string, unknown>;
  provider_data?: Record<string, unknown> | null;
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
  role: string;
  content: ContentBlock[];
  provider_data?: Record<string, unknown> | null;
}

export interface SystemPart {
  type: "text";
  text: string;
  cache_hint?: Record<string, unknown> | null;
  provider_data?: Record<string, unknown> | null;
}

export interface ToolDef {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  provider_data?: Record<string, unknown> | null;
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
  content: Array<TextBlock | ToolUseBlock | ThinkingBlock | UnknownBlock>;
  provider_extras: Record<string, unknown>;
}
