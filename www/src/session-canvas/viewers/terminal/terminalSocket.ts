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
}

const WEBSOCKET_OPEN = 1;

/** Normalize an inbound binary frame to bytes without a realm-bound instanceof. */
function toBytes(data: ArrayBuffer | ArrayBufferView): Uint8Array {
  if (ArrayBuffer.isView(data)) {
    return new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
  }
  return new Uint8Array(data);
}

/** Same-origin ws(s):// URL for the backend terminal endpoint. */
export function terminalSocketUrl(
  location: { protocol: string; host: string } = window.location,
): string {
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${location.host}/api/v1/terminal`;
}

export function openTerminalSocket(
  term: TerminalIO,
  options: OpenTerminalSocketOptions = {},
): TerminalSocket {
  const url = options.url ?? terminalSocketUrl();
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
    socket.send(payload);
  };

  socket.onopen = () => {
    const queued = outbox ?? [];
    outbox = null;
    for (const payload of queued) socket.send(payload);
  };

  socket.onmessage = (event) => {
    // Binary frames are raw PTY output; a string frame would be an out-of-band
    // control echo we never opt into, so ignore it. `instanceof ArrayBuffer` is
    // unreliable across realms (jsdom/worker), so detect by exclusion instead.
    const { data } = event;
    if (typeof data === "string" || data == null) return;
    term.write(toBytes(data as ArrayBuffer | ArrayBufferView));
  };

  const subscription = term.onData((data) => send(encoder.encode(data)));

  return {
    sendResize(cols, rows) {
      send(JSON.stringify({ type: "resize", cols, rows }));
    },
    close() {
      subscription.dispose();
      socket.onopen = null;
      socket.onmessage = null;
      socket.close();
    },
  };
}
