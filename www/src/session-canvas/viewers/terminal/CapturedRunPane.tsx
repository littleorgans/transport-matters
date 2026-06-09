import { type ReactElement, useCallback, useState } from "react";
import type { CliName } from "../../../types";
import { cliLabel } from "../../model/paneRecords";
import { type CapturedRunErrorFrame, parseCapturedRunFrame } from "./capturedRunFrames";
import { closedMessage, useTerminalSession } from "./terminalSession";
import { capturedTerminalSocketUrl } from "./terminalSocket";
import "./terminal-pane.css";

export interface CapturedRunPaneProps {
  /** Managed CLI to launch as a captured run; selects the terminal endpoint. */
  provider: CliName;
  /** Absolute working directory; omitted lets the backend resolve its workspace. */
  cwd?: string;
}

/**
 * A captured managed-CLI session (Claude or Codex) in a canvas pane: the desktop
 * equivalent of `transport-matters {provider}`, with the agent's traffic routed
 * through the TM reverse proxy. It reuses the shared terminal session core (xterm
 * + PTY socket); only the provider endpoint and the launch-error wire frame differ
 * from the bare TerminalPane. The pane reads as a plain terminal surface — its
 * captured identity lives in the window title (the provider name); a launch
 * failure surfaces as an alert banner over the surface.
 */
export function CapturedRunPane({ provider, cwd }: CapturedRunPaneProps): ReactElement {
  const [errorFrame, setErrorFrame] = useState<CapturedRunErrorFrame | null>(null);

  const buildUrl = useCallback(
    (cols: number, rows: number) => capturedTerminalSocketUrl(provider, cols, rows, cwd),
    [provider, cwd],
  );
  // The ready frame carries run metadata, but the pane no longer shows it (the
  // window title is the only chrome); only a launch error needs to surface.
  const onTextFrame = useCallback((text: string) => {
    const frame = parseCapturedRunFrame(text);
    if (frame?.type === "captured-run.error") setErrorFrame(frame);
  }, []);

  const { surfaceRef, closedCode } = useTerminalSession({ buildUrl, onTextFrame });
  const status = capturedStatus(provider, errorFrame, closedCode);

  return (
    <div className="terminal-pane">
      <div className="terminal-pane__surface" ref={surfaceRef} />
      {status === null ? null : (
        <p className="terminal-pane__status" role="alert">
          {status}
        </p>
      )}
    </div>
  );
}

/** A launch-error frame wins over a plain socket close; both surface as a banner. */
function capturedStatus(
  provider: CliName,
  error: CapturedRunErrorFrame | null,
  closedCode: number | null,
): string | null {
  if (error) return `Captured run failed (${error.code}): ${error.message}`;
  if (closedCode !== null) return closedMessage(closedCode, cliLabel(provider));
  return null;
}
