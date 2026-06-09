// Typed inbound JSON frames for the captured Claude terminal WebSocket. The
// backend (api/v1/captured_terminal.py) sends exactly one `captured-run.ready`
// text frame before any PTY bytes, and a `captured-run.error` text frame if the
// launch fails. Field names and casing mirror the backend `_ready_frame` /
// `_send_error_and_close` payloads exactly; bind here, do not assume.

export interface CapturedRunReadyFrame {
  type: "captured-run.ready";
  runId: string;
  cwd: string;
  storageDir: string;
  proxyPort: number | null;
  webPort: number;
  cli: string;
  nativeSessionId?: string;
}

export interface CapturedRunErrorFrame {
  type: "captured-run.error";
  code: string;
  message: string;
}

export type CapturedRunFrame = CapturedRunReadyFrame | CapturedRunErrorFrame;

/**
 * Parse one inbound text frame into a captured-run frame, or null if it is not a
 * recognized captured-run control frame (raw PTY bytes never arrive here as text,
 * so anything unparseable is dropped rather than surfaced).
 */
export function parseCapturedRunFrame(text: string): CapturedRunFrame | null {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null) return null;
  const frame = value as Record<string, unknown>;

  if (frame.type === "captured-run.ready" && typeof frame.runId === "string") {
    const ready: CapturedRunReadyFrame = {
      type: "captured-run.ready",
      runId: frame.runId,
      cwd: asString(frame.cwd),
      storageDir: asString(frame.storageDir),
      proxyPort: typeof frame.proxyPort === "number" ? frame.proxyPort : null,
      webPort: typeof frame.webPort === "number" ? frame.webPort : 0,
      cli: asString(frame.cli),
    };
    if (typeof frame.nativeSessionId === "string") ready.nativeSessionId = frame.nativeSessionId;
    return ready;
  }

  if (frame.type === "captured-run.error" && typeof frame.code === "string") {
    return { type: "captured-run.error", code: frame.code, message: asString(frame.message) };
  }

  return null;
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}
