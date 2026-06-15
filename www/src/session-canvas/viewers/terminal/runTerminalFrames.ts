// Typed inbound JSON control frames for the managed-run terminal WebSocket
// (api/v1/run_routes.py). The backend sends a `run.terminal.ready` frame, then
// scrollback bytes, then `run.terminal.scrollback-end` before live PTY output,
// and a `run.error` frame on any attach/runtime failure (run_not_found,
// run_not_attachable, run_terminated, run_stale, ...). The captured pane only
// needs to surface errors; field names mirror the backend `run.error` payload exactly.

export interface RunErrorFrame {
  type: "run.error";
  code: string;
  message: string;
}

/**
 * Parse one inbound text frame into a run.error frame, or null if it is not a
 * recognized error control frame (the ready/scrollback frames and raw PTY bytes
 * are not errors, so they are dropped rather than surfaced as a banner).
 */
export function parseRunErrorFrame(text: string): RunErrorFrame | null {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null) return null;
  const frame = value as Record<string, unknown>;

  if (frame.type === "run.error" && typeof frame.code === "string") {
    return { type: "run.error", code: frame.code, message: asString(frame.message) };
  }
  return null;
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}
