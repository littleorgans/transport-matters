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
