import type { PausedFlow } from "../../../src/types";
import { PAUSED_AT_MS } from "./time";

export const mockPausedFlow: PausedFlow = {
  flow_id: "c740eb90-abcd-4321-9876-deadbeef0000",
  transport: "http",
  paused_at_ms: PAUSED_AT_MS,
  ir: {
    model: "claude-haiku-4-5-20251001",
    provider: "anthropic",
    system: [{ type: "text", text: "you are a helpful assistant." }],
    tools: [],
    messages: [{ role: "user", content: [{ type: "text", text: "Hello there" }] }],
    sampling: {
      max_tokens: 32000,
      temperature: 1,
      top_p: null,
      top_k: null,
      stop_sequences: [],
    },
    metadata: {
      session_id: null,
      device_id: null,
      account_id: null,
      provider_metadata: {},
    },
    stream: false,
    provider_extras: {},
  },
  original_tools: [],
  original_system: [{ type: "text", text: "you are a helpful assistant." }],
  original_messages: [{ role: "user", content: [{ type: "text", text: "Hello there" }] }],
  original_sampling: {
    max_tokens: 32000,
    temperature: 1,
    top_p: null,
    top_k: null,
    stop_sequences: [],
  },
  original_provider_extras: {},
  audit: null,
  tokens_before: null,
};
