import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { type ReactElement, useEffect, useRef, useState } from "react";
import { openTerminalSocket, terminalSocketUrl } from "./terminalSocket";
import "./terminal-pane.css";

/**
 * Interactive local shell. Mounts an xterm terminal and bridges it to the
 * backend PTY over a WebSocket (see terminalSocket for the wire protocol).
 * The terminal and the socket are created on mount and fully torn down on
 * unmount so a closed pane leaves nothing running. Each mounted instance owns
 * its own shell, so multiple terminal panes run independently.
 */
export function TerminalPane(): ReactElement {
  const surfaceRef = useRef<HTMLDivElement>(null);
  // Non-null once the socket closes involuntarily (refused / lost). The
  // deliberate unmount close detaches the handler, so it never lands here.
  const [closedCode, setClosedCode] = useState<number | null>(null);

  useEffect(() => {
    const surface = surfaceRef.current;
    if (!surface) return;

    const term = new Terminal({
      cursorBlink: true,
      fontFamily: readToken(surface, "--font-mono", "ui-monospace, monospace"),
      fontSize: 13,
      theme: {
        background: readToken(surface, "--color-well", "#040404"),
        foreground: readToken(surface, "--color-txt", "#dcdcdc"),
      },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(surface);
    fit.fit();

    let disposed = false;
    const socket = openTerminalSocket(term, {
      url: terminalSocketUrl(term.cols, term.rows),
      onStatus: (status, info) => {
        if (disposed) return;
        setClosedCode(status === "open" ? null : (info?.code ?? 1006));
      },
    });
    socket.sendResize(term.cols, term.rows);

    // Re-fit when the pane is resized so the backend PTY tracks the viewport.
    const observer = new ResizeObserver(() => {
      fit.fit();
      socket.sendResize(term.cols, term.rows);
    });
    observer.observe(surface);

    return () => {
      disposed = true;
      observer.disconnect();
      socket.close();
      term.dispose();
    };
  }, []);

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

/** Human-readable reason for an involuntary socket close. */
function closedMessage(code: number): string {
  if (code === 1008) return "Terminal connection refused (origin not allowed).";
  return "Terminal connection closed. Reopen the pane to retry.";
}

/** A canvas cannot resolve CSS variables, so read the token off the host. */
function readToken(host: HTMLElement, name: string, fallback: string): string {
  const value = getComputedStyle(host).getPropertyValue(name).trim();
  return value.length > 0 ? value : fallback;
}
