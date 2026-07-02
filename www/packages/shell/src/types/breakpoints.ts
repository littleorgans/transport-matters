import type { SpawnAnchor, TrackRole } from "./exchanges";
import type { InternalRequest, Message, SamplingParams, SystemPart, ToolDef } from "./ir";
import type { OverrideAudit } from "./overrides";

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

export interface BreakpointStatusDetail {
  mode: "off" | "armed_once";
  paused_flows: Array<{ flow_id: string; paused_at_ms: number }>;
}
