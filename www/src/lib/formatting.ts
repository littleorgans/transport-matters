import type { UsageStats } from "../types";

export const PREVIEW_MAX = 220;

export function displayModel(provider: string, model: string): string {
  const prefix = `${provider}/`;
  return model.startsWith(prefix) ? model.slice(prefix.length) : model;
}

export function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return `${count.toLocaleString()} ${count === 1 ? singular : plural}`;
}

export function formatCompactChars(value: number): string {
  return value >= 1024 ? `${(value / 1024).toFixed(1)}K` : value.toLocaleString();
}

export function formatClockTime(ts: string | Date | null | undefined): string | null {
  if (!ts) return null;
  const parsed = ts instanceof Date ? ts : new Date(ts);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function truncatePreview(text: string, maxPreview = PREVIEW_MAX): string {
  return text.length <= maxPreview ? text : `${text.slice(0, maxPreview)}…`;
}

export function formatRelativeAge(ts: string, nowMs = Date.now()): string {
  const parsed = new Date(ts);
  if (Number.isNaN(parsed.getTime())) return ts;

  const diffMs = Math.max(0, nowMs - parsed.getTime());
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (diffMs < minute) return "just now";
  if (diffMs < hour) return `${Math.floor(diffMs / minute)}m ago`;
  if (diffMs < day) return `${Math.floor(diffMs / hour)}h ago`;
  if (diffMs < 7 * day) return `${Math.floor(diffMs / day)}d ago`;

  // Use the UTC ISO calendar date so every caller shares one deterministic
  // >=7d fallback independent of browser locale and local timezone.
  return parsed.toISOString().slice(0, 10);
}

/**
 * Compact working-directory label for narrow metadata rails.
 *
 * Full absolute paths are too noisy for a single-line header cell, but a
 * bare basename often loses the useful namespace when several sibling repos
 * share similar names. Keep the final two path segments where possible and
 * let the caller expose the full path via `title`.
 */
export function displayCwd(cwd: string): string {
  const trimmed = cwd.replace(/[\\/]+$/, "");
  if (trimmed === "") return cwd || "/";

  const parts = trimmed.split(/[\\/]/).filter(Boolean);
  if (parts.length === 1) return parts[0] ?? trimmed;
  return parts.slice(-2).join("/");
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
