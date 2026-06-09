import { type ReactElement, useCallback, useState } from "react";
import {
  type CapturedRunErrorFrame,
  type CapturedRunReadyFrame,
  parseCapturedRunFrame,
} from "./capturedRunFrames";
import { closedMessage, useTerminalSession } from "./terminalSession";
import { capturedTerminalSocketUrl } from "./terminalSocket";
import "./terminal-pane.css";
import "./captured-claude-pane.css";

export interface CapturedClaudePaneProps {
  /** Absolute working directory; omitted lets the backend resolve its workspace. */
  cwd?: string;
}

/**
 * A captured Claude Code session in a canvas pane: the desktop equivalent of
 * `transport-matters claude`, with the agent's traffic routed through the TM
 * reverse proxy. It reuses the shared terminal session core (xterm + PTY socket);
 * only the endpoint, the ready/error wire frames, and the captured header differ
 * from the bare TerminalPane. The header marks the pane as a captured run and
 * surfaces the run id once the backend ready frame lands, so it reads as visibly
 * distinct from a local terminal.
 */
export function CapturedClaudePane({ cwd }: CapturedClaudePaneProps): ReactElement {
  const [ready, setReady] = useState<CapturedRunReadyFrame | null>(null);
  const [errorFrame, setErrorFrame] = useState<CapturedRunErrorFrame | null>(null);

  const buildUrl = useCallback(
    (cols: number, rows: number) => capturedTerminalSocketUrl(cols, rows, cwd),
    [cwd],
  );
  const onTextFrame = useCallback((text: string) => {
    const frame = parseCapturedRunFrame(text);
    if (!frame) return;
    if (frame.type === "captured-run.ready") setReady(frame);
    else setErrorFrame(frame);
  }, []);

  const { surfaceRef, closedCode } = useTerminalSession({ buildUrl, onTextFrame });
  const status = capturedStatus(errorFrame, closedCode);

  return (
    <div className="captured-pane">
      <header className="captured-pane__header">
        <span className="captured-pane__badge">captured</span>
        <span className="captured-pane__meta">{readyLabel(ready)}</span>
      </header>
      <div className="terminal-pane captured-pane__body">
        <div className="terminal-pane__surface" ref={surfaceRef} />
        {status === null ? null : (
          <p className="terminal-pane__status" role="alert">
            {status}
          </p>
        )}
      </div>
    </div>
  );
}

/** Header meta: a starting hint until the ready frame lands, then the run id. */
function readyLabel(ready: CapturedRunReadyFrame | null): string {
  if (!ready) return "Starting captured Claude…";
  return `Claude · run ${ready.runId.slice(0, 8)}`;
}

/** A launch-error frame wins over a plain socket close; both surface as a banner. */
function capturedStatus(
  error: CapturedRunErrorFrame | null,
  closedCode: number | null,
): string | null {
  if (error) return `Captured run failed (${error.code}): ${error.message}`;
  if (closedCode !== null) return closedMessage(closedCode, "Claude");
  return null;
}
