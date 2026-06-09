import type { ReactElement } from "react";
import { closedMessage, useTerminalSession } from "./terminalSession";
import { terminalSocketUrl } from "./terminalSocket";
import "./terminal-pane.css";

/**
 * Interactive local shell. Mounts an xterm terminal and bridges it to the
 * backend PTY over a WebSocket (see terminalSocket for the wire protocol).
 * The terminal and the socket are created on mount and fully torn down on
 * unmount so a closed pane leaves nothing running. Each mounted instance owns
 * its own shell, so multiple terminal panes run independently.
 */
export function TerminalPane(): ReactElement {
  const { surfaceRef, closedCode } = useTerminalSession({ buildUrl: terminalSocketUrl });

  return (
    <div className="terminal-pane">
      <div className="terminal-pane__surface" ref={surfaceRef} />
      {closedCode === null ? null : (
        <p className="terminal-pane__status" role="alert">
          {closedMessage(closedCode)}
        </p>
      )}
    </div>
  );
}
