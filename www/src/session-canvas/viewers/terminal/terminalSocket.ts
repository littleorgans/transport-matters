// Wire protocol for the terminal pane: one WebSocket bridging xterm to a backend
// PTY. Binary frames are raw PTY I/O in both directions; a JSON text frame
// ({type:"resize",cols,rows}) carries window-size changes. The xterm surface and
// the socket constructor are both injected so the protocol is unit-testable
// without a real terminal or a live server (the component wires the real ones).

/** The slice of xterm's Terminal this module touches. */
export interface TerminalIO {
  onData(handler: (data: string) => void): { dispose(): void };
  write(data: Uint8Array): void;
}

export interface TerminalSocket {
  /** Send a resize control frame so the backend PTY matches the viewport. */
  sendResize(cols: number, rows: number): void;
  /** Detach the data subscription and close the socket. */
  close(): void;
}

export type SocketFactory = (url: string) => WebSocket;

interface OpenTerminalSocketOptions {
  url?: string;
  socketFactory?: SocketFactory;
  /** Connection lifecycle, so the pane can surface a refused/closed state. */
  onStatus?: (status: "open" | "closed", info?: { code: number; reason: string }) => void;
  /**
   * Inbound JSON text frames (e.g. the captured-run ready/error frames). The bare
   * terminal omits this, so out-of-band control echoes stay ignored rather than
   * being written to the screen.
   */
  onTextFrame?: (text: string) => void;
}

const WEBSOCKET_OPEN = 1;

/** Normalize an inbound binary frame to bytes without a realm-bound instanceof. */
function toBytes(data: ArrayBuffer | ArrayBufferView): Uint8Array {
  if (ArrayBuffer.isView(data)) {
    return new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
  }
  return new Uint8Array(data);
}

type SocketLocation = { protocol: string; host: string };

/** ws(s):// scheme for the current page protocol. */
function socketScheme(location: SocketLocation): string {
  return location.protocol === "https:" ? "wss:" : "ws:";
}

/** Same-origin ws(s):// URL for the backend terminal endpoint, seeded with the PTY size. */
export function terminalSocketUrl(
  cols: number,
  rows: number,
  location: SocketLocation = window.location,
): string {
  return `${socketScheme(location)}//${location.host}/api/terminal?cols=${cols}&rows=${rows}`;
}

/**
 * Same-origin ws(s):// URL that attaches to an already-spawned managed run's PTY
 * (`/v1/runs/{runId}/terminal`, see api/v1/run_routes.py). The run is created
 * out of band via `POST /v1/runs`; this socket only attaches, so closing it
 * detaches the viewer and leaves the run running headless.
 */
export function runTerminalSocketUrl(
  runId: string,
  cols: number,
  rows: number,
  location: SocketLocation = window.location,
): string {
  const runSegment = encodeURIComponent(runId);
  return `${socketScheme(location)}//${location.host}/v1/runs/${runSegment}/terminal?cols=${cols}&rows=${rows}`;
}

export function openTerminalSocket(
  term: TerminalIO,
  options: OpenTerminalSocketOptions = {},
): TerminalSocket {
  const url = options.url ?? terminalSocketUrl(80, 24);
  const createSocket = options.socketFactory ?? ((target) => new WebSocket(target));
  const socket = createSocket(url);
  socket.binaryType = "arraybuffer";

  const encoder = new TextEncoder();
  // PTY input may be typed before the socket finishes opening; queue it so no
  // keystroke is dropped, then flush in order once the connection is live.
  let outbox: Array<string | Uint8Array> | null = socket.readyState === WEBSOCKET_OPEN ? null : [];

  const send = (payload: string | Uint8Array): void => {
    if (outbox) {
      outbox.push(payload);
      return;
    }
    // Drop input once the socket is closing/closed; calling send() on a
    // non-OPEN socket throws InvalidStateError (e.g. typing after the PTY exits).
    if (socket.readyState === WEBSOCKET_OPEN) socket.send(payload);
  };

  socket.onopen = () => {
    const queued = outbox ?? [];
    outbox = null;
    for (const payload of queued) socket.send(payload);
    options.onStatus?.("open");
  };

  socket.onclose = (event) => {
    options.onStatus?.("closed", { code: event.code, reason: event.reason });
  };

  // A failed handshake (server down, refused) may fire onerror without a useful
  // close code; surface it as a generic abnormal close so the pane still reacts.
  socket.onerror = () => options.onStatus?.("closed", { code: 1006, reason: "error" });

  socket.onmessage = (event) => {
    // Binary frames are raw PTY output. A string frame is an out-of-band control
    // message (e.g. a captured-run ready/error frame): hand it to onTextFrame,
    // never to the screen. `instanceof ArrayBuffer` is unreliable across realms
    // (jsdom/worker), so detect strings by exclusion instead.
    const { data } = event;
    if (data == null) return;
    if (typeof data === "string") {
      options.onTextFrame?.(data);
      return;
    }
    term.write(toBytes(data as ArrayBuffer | ArrayBufferView));
  };

  const subscription = term.onData((data) => send(encoder.encode(data)));

  return {
    sendResize(cols, rows) {
      send(JSON.stringify({ type: "resize", cols, rows }));
    },
    close() {
      subscription.dispose();
      // Detach handlers first so the deliberate teardown never reports as a
      // refused/closed connection to the pane.
      socket.onopen = null;
      socket.onmessage = null;
      socket.onclose = null;
      socket.onerror = null;
      socket.close();
    },
  };
}
