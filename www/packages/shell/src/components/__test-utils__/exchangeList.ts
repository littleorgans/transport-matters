import type { IndexEntry, ResStats } from "@tm/core/types/exchanges";

export const legacyClaudeRes: ResStats = {
  stop_reason: "end_turn",
  input_tokens: 100,
  output_tokens: 50,
  cache_creation_input_tokens: 0,
  cache_read_input_tokens: 0,
  text_chars: 200,
  tool_calls: 0,
};

export function makeEntry(overrides: Partial<IndexEntry> = {}): IndexEntry {
  return {
    id: "test-001",
    ts: "2026-04-26T00:00:00.000Z",
    provider: "anthropic",
    model: "anthropic/claude-sonnet-4-20250514",
    path: "exchanges/test/",
    req: {
      system_parts: 1,
      system_chars: 100,
      tools_count: 3,
      tools_chars: 500,
      messages_count: 2,
      messages_chars: 200,
      total_chars: 800,
    },
    res: null,
    pipeline: null,
    mutated_manually: false,
    ...overrides,
  };
}
