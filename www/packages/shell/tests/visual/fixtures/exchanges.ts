import type { IndexEntry } from "@tm/core/types/exchanges";
import { FROZEN_NOW } from "./time";

type VisualExchangeFixtures = [IndexEntry, IndexEntry, IndexEntry, IndexEntry, IndexEntry];
type AnchoredVisualExchangeFixtures = [IndexEntry, IndexEntry, IndexEntry];

export const mockVisualRunId = "visual-run";
export const mockAnchoredSubagentId = "2222cccc-1111-2222-3333-444455556666";
const visualParentTrack = {
  run_id: mockVisualRunId,
  track_id: mockVisualRunId,
  parent_track_id: null,
  track_role: "parent",
} satisfies Partial<IndexEntry>;

export const mockExchanges: VisualExchangeFixtures = [
  {
    id: "aaaabbbb-1111-2222-3333-444455556666",
    ts: new Date(FROZEN_NOW.getTime() - 60_000).toISOString(),
    provider: "anthropic",
    model: "claude-sonnet-4-5",
    path: "",
    req: {
      system_parts: 1,
      system_chars: 29,
      tools_count: 4,
      tools_chars: 3_420,
      messages_count: 3,
      messages_chars: 8_551,
      total_chars: 12_000,
    },
    pipeline: null,
    res: {
      stop_reason: "end_turn",
      input_tokens: 3_208,
      output_tokens: 412,
      cache_creation_input_tokens: 0,
      cache_read_input_tokens: 1_144,
      text_chars: 1_982,
      tool_calls: 2,
    },
    mutated_manually: false,
  },
  {
    id: "ddddeeee-1111-2222-3333-444455556666",
    ts: new Date(FROZEN_NOW.getTime() - 600_000).toISOString(),
    provider: "openai",
    model: "gpt-4o",
    path: "",
    req: {
      system_parts: 1,
      system_chars: 41,
      tools_count: 2,
      tools_chars: 1_280,
      messages_count: 4,
      messages_chars: 6_479,
      total_chars: 7_800,
    },
    pipeline: null,
    res: {
      stop_reason: "end_turn",
      input_tokens: 2_112,
      output_tokens: 228,
      cache_creation_input_tokens: 0,
      cache_read_input_tokens: 0,
      text_chars: 1_131,
      tool_calls: 1,
    },
    mutated_manually: true,
  },
  {
    id: "ffff0000-1111-2222-3333-444455556666",
    ts: new Date(FROZEN_NOW.getTime() - 1_860_000).toISOString(),
    provider: "codex",
    model: "codex/gpt-5-codex",
    path: "runs/codex-session-01",
    req: {
      system_parts: 0,
      system_chars: 0,
      tools_count: 2,
      tools_chars: 842,
      messages_count: 2,
      messages_chars: 1_778,
      total_chars: 2_620,
    },
    pipeline: null,
    res: {
      stop_reason: "completed",
      input_tokens: 1_048,
      output_tokens: 164,
      cache_creation_input_tokens: 0,
      cache_read_input_tokens: 0,
      text_chars: 41,
      tool_calls: 0,
    },
    mutated_manually: false,
  },
  {
    id: "8888bbbb-1111-2222-3333-444455556666",
    ts: new Date(FROZEN_NOW.getTime() - 2_640_000).toISOString(),
    provider: "codex",
    model: "codex/gpt-5-codex",
    path: "runs/codex-session-03",
    req: {
      system_parts: 0,
      system_chars: 0,
      tools_count: 1,
      tools_chars: 144,
      messages_count: 1,
      messages_chars: 92,
      total_chars: 236,
    },
    pipeline: null,
    res: null,
    mutated_manually: false,
  },
  {
    id: "9999aaaa-1111-2222-3333-444455556666",
    ts: new Date(FROZEN_NOW.getTime() - 3_780_000).toISOString(),
    provider: "codex",
    model: "codex/transport-handshake",
    path: "runs/codex-session-02",
    req: {
      system_parts: 0,
      system_chars: 0,
      tools_count: 0,
      tools_chars: 0,
      messages_count: 1,
      messages_chars: 72,
      total_chars: 72,
    },
    pipeline: null,
    res: null,
    mutated_manually: false,
  },
];

export const mockAnchoredSpawnExchangeId = mockExchanges[1].id;

export const mockAnchoredExchanges: AnchoredVisualExchangeFixtures = [
  {
    ...mockExchanges[0],
    ...visualParentTrack,
  },
  {
    ...mockExchanges[1],
    ...visualParentTrack,
  },
  {
    id: mockAnchoredSubagentId,
    run_id: mockVisualRunId,
    track_id: "toolu_visual_research",
    parent_track_id: mockVisualRunId,
    track_display_name: "Research",
    track_role: "subagent",
    spawn_anchor: {
      track_spawn_exchange_id: mockAnchoredSpawnExchangeId,
      track_spawn_tool_use_id: "toolu_visual_research",
      track_spawn_order: 0,
    },
    ts: new Date(FROZEN_NOW.getTime() - 420_000).toISOString(),
    provider: "anthropic",
    model: "claude-sonnet-4-5",
    path: "",
    req: {
      system_parts: 1,
      system_chars: 21,
      tools_count: 2,
      tools_chars: 1_482,
      messages_count: 2,
      messages_chars: 3_924,
      total_chars: 5_427,
    },
    pipeline: null,
    res: {
      stop_reason: "end_turn",
      input_tokens: 1_680,
      output_tokens: 286,
      cache_creation_input_tokens: 0,
      cache_read_input_tokens: 420,
      text_chars: 1_204,
      tool_calls: 1,
    },
    mutated_manually: false,
  },
];

export const mockCodexTransportSuccessId = mockExchanges[2].id;
export const mockCodexTimelineOpenId = mockExchanges[3].id;
export const mockCodexTransportDiagnosticId = mockExchanges[4].id;
