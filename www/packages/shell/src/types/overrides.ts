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
   * Populated for text-bearing kinds when applied is true. Toggle and scalar
   * kinds leave this null. The Inspect tab uses it to synthesize read-only
   * overrides against the original IR without replaying the server pop
   * cascade when block toggles shift later targets.
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
