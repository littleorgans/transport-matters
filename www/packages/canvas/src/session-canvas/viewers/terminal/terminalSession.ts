import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { useEffect, useRef, useState } from "react";
import { registerPasteHandle } from "./pasteRegistry";
import { openTerminalSocket } from "./terminalSocket";

// Shared core for every terminal-backed pane: it mounts an xterm surface, opens
// the PTY WebSocket, keeps the backend PTY sized to the viewport, and tears the
// whole thing down on unmount so a closed pane leaves nothing running. Variants
// (bare Terminal, captured Claude) differ only in the endpoint URL, the inbound
// text-frame handling, and their chrome — they wrap this hook instead of copying
// it. Mirrors the backend split (shared terminal_bridge + thin route variants).

export interface TerminalSessionOptions {
  /** Build the ws(s):// endpoint URL once the surface is fitted to its size. */
  buildUrl: (cols: number, rows: number) => string;
  /** Receive inbound JSON text frames (captured-run ready/error). Bare terminal omits it. */
  onTextFrame?: (text: string) => void;
  /** Receive the first ordinary PTY output frame. */
  onOutput?: () => void;
  /** Registers a drop-paste handle for this pane while mounted. */
  paneId?: string;
  /**
   * Captured runs: the backend bridge answers the harness OSC 10/11 color
   * queries (api: osc_color_responder), so xterm must not answer too or a
   * focus-event requery lets the viewer shout over the bridge. Set-color
   * payloads still reach xterm; only the "?" queries are swallowed.
   */
  suppressColorQueryReplies?: boolean;
}

/**
 * Owns one xterm + one PTY socket for the lifetime of the mounted pane. Returns
 * the surface ref to attach and the involuntary-close code (non-null once the
 * socket is refused/lost; a deliberate unmount close detaches the handler so it
 * never lands here).
 */
export function useTerminalSession({
  buildUrl,
  onOutput,
  onTextFrame,
  paneId,
  suppressColorQueryReplies,
}: TerminalSessionOptions) {
  const surfaceRef = useRef<HTMLDivElement>(null);
  const [closedCode, setClosedCode] = useState<number | null>(null);
  // The socket is created once on mount; read the latest callbacks off refs so
  // the effect stays a one-shot without re-subscribing on every render.
  const buildUrlRef = useRef(buildUrl);
  buildUrlRef.current = buildUrl;
  const onTextFrameRef = useRef(onTextFrame);
  onTextFrameRef.current = onTextFrame;
  const onOutputRef = useRef(onOutput);
  onOutputRef.current = onOutput;
  const suppressColorRef = useRef(suppressColorQueryReplies);
  suppressColorRef.current = suppressColorQueryReplies;

  useEffect(() => {
    const surface = surfaceRef.current;
    if (!surface) return;

    const term = new Terminal({
      // The terminal surface is transparent: the pane window behind it owns
      // the fill through the themed veil (--pane-surface-alpha), so terminals
      // pick up theme and glass changes live like every other pane interior.
      allowTransparency: true,
      cursorBlink: true,
      fontFamily: readToken(surface, "--font-mono", "ui-monospace, monospace"),
      fontSize: 13,
      theme: {
        background: "#00000000",
        foreground: readToken(surface, "--color-txt", "#dcdcdc"),
      },
    });
    if (suppressColorRef.current) {
      // True swallows the query (the bridge answers it); false on anything
      // else lets xterm's default handler apply real set-color payloads.
      term.parser.registerOscHandler(10, (data) => data === "?");
      term.parser.registerOscHandler(11, (data) => data === "?");
    }
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(surface);
    fit.fit();
    // Focus the new pane so it's typeable immediately and control keys (Ctrl-C,
    // Ctrl-D, ...) reach the PTY instead of the browser. xterm only emits keys
    // via onData while its textarea holds focus.
    term.focus();
    const unregisterPaste =
      paneId === undefined ? null : registerPasteHandle(paneId, (text) => term.paste(text));

    // Copy on select. Cmd+C needs a `copy` event to reach xterm's hidden
    // textarea, which pane focus handling can starve; writing the clipboard as
    // the selection settles skips that chain. The hasSelection guard keeps a
    // cleared selection from clobbering the clipboard with an empty string.
    // Disposed with the terminal via term.dispose().
    term.onSelectionChange(() => {
      if (!term.hasSelection()) return;
      void navigator.clipboard?.writeText(term.getSelection()).catch(() => {});
    });

    let disposed = false;
    const socket = openTerminalSocket(term, {
      url: buildUrlRef.current(term.cols, term.rows),
      onStatus: (status, info) => {
        if (disposed) return;
        setClosedCode(status === "open" ? null : (info?.code ?? 1006));
      },
      onTextFrame: (text) => {
        if (!disposed) onTextFrameRef.current?.(text);
      },
      onOutput: () => {
        if (!disposed) onOutputRef.current?.();
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
      unregisterPaste?.();
      term.dispose();
    };
    // paneId is stable for a mounted pane, so the effect stays one-shot.
  }, [paneId]);

  return { surfaceRef, closedCode };
}

/** Human-readable reason for an involuntary socket close. */
export function closedMessage(code: number, subject = "Terminal"): string {
  if (code === 1008) return `${subject} connection refused (origin not allowed).`;
  return `${subject} connection closed. Reopen the pane to retry.`;
}

/** A canvas cannot resolve CSS variables, so read the token off the host. */
function readToken(host: HTMLElement, name: string, fallback: string): string {
  const value = getComputedStyle(host).getPropertyValue(name).trim();
  return value.length > 0 ? value : fallback;
}
