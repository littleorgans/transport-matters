import type { UsageStats } from "../types";

export function displayModel(provider: string, model: string): string {
  const prefix = `${provider}/`;
  return model.startsWith(prefix) ? model.slice(prefix.length) : model;
}

/**
 * Context tokens fill the model's window. Formula is
 * `input + cache_creation + cache_read`, matching the Anthropic
 * statusline and every other place the API exposes a context figure.
 *
 * output_tokens are excluded because they measure generation. The UI
 * surfaces them as a separate metric (TokenBar's "+N tokens generated"
 * line, list-row readouts, etc).
 *
 * Returns 0 for a null source, which happens when a row is awaiting
 * its response or predates the counter wiring.
 */
export function contextTokens(src: UsageStats | null): number {
  if (!src) return 0;
  return src.input_tokens + src.cache_creation_input_tokens + src.cache_read_input_tokens;
}
