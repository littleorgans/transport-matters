import { describe, expect, it, vi } from "vitest";
import { openTerminalSocket, type TerminalIO, terminalSocketUrl } from "./terminalSocket";

const OPEN = 1;
const CONNECTING = 0;

/** Minimal stand-in for the browser WebSocket, recording everything sent. */
class FakeSocket {
  binaryType = "blob";
  readyState = OPEN;
  onopen: ((ev: unknown) => void) | null = null;
  onmessage: ((ev: { data: unknown }) => void) | null = null;
  onclose: ((ev: unknown) => void) | null = null;
  onerror: ((ev: unknown) => void) | null = null;
  sent: unknown[] = [];
  send = vi.fn((data: unknown) => {
    // Mirror the browser: send() on a non-OPEN socket throws InvalidStateError.
    if (this.readyState !== OPEN) throw new Error("InvalidStateError");
    this.sent.push(data);
  });
  close = vi.fn(() => {
    this.readyState = 3;
  });
  constructor(readonly url: string) {}
  emit(data: unknown): void {
    this.onmessage?.({ data });
  }
  open(): void {
    this.readyState = OPEN;
    this.onopen?.({});
  }
  emitClose(code: number): void {
    this.readyState = 3;
    this.onclose?.({ code, reason: "" });
  }
}

/** Captures the xterm surface the socket touches without pulling in real xterm. */
class FakeTerm implements TerminalIO {
  written: Uint8Array[] = [];
  disposed = false;
  private handler: ((data: string) => void) | null = null;
  onData(cb: (data: string) => void): { dispose(): void } {
    this.handler = cb;
    return {
      dispose: () => {
        this.disposed = true;
      },
    };
  }
  write(data: Uint8Array): void {
    this.written.push(data);
  }
  type(data: string): void {
    this.handler?.(data);
  }
}

function decode(value: unknown): string {
  return new TextDecoder().decode(value as Uint8Array);
}

describe("terminalSocketUrl", () => {
  it("derives a same-origin ws:// url with the size query for http pages", () => {
    expect(terminalSocketUrl(80, 24, { protocol: "http:", host: "localhost:5173" })).toBe(
      "ws://localhost:5173/api/v1/terminal?cols=80&rows=24",
    );
  });

  it("upgrades to wss:// on https pages and carries the fitted size", () => {
    expect(terminalSocketUrl(120, 40, { protocol: "https:", host: "app.example.com" })).toBe(
      "wss://app.example.com/api/v1/terminal?cols=120&rows=40",
    );
  });
});

describe("openTerminalSocket", () => {
  function setup(readyState = OPEN) {
    const term = new FakeTerm();
    const sockets: FakeSocket[] = [];
    const socketFactory = (url: string) => {
      const socket = new FakeSocket(url);
      socket.readyState = readyState;
      sockets.push(socket);
      return socket as unknown as WebSocket;
    };
    const statuses: Array<{ status: "open" | "closed"; code?: number }> = [];
    const api = openTerminalSocket(term, {
      url: "ws://host/api/v1/terminal",
      socketFactory,
      onStatus: (status, info) => statuses.push({ status, code: info?.code }),
    });
    const socket = sockets[0];
    if (!socket) throw new Error("expected a socket to be created");
    return { term, socket, api, statuses };
  }

  it("opens one socket and requests arraybuffer binary frames", () => {
    const { socket } = setup();
    expect(socket.url).toBe("ws://host/api/v1/terminal");
    expect(socket.binaryType).toBe("arraybuffer");
  });

  it("forwards typed input as raw bytes (onData -> ws.send)", () => {
    const { term, socket } = setup();
    term.type("ls -la\n");
    expect(socket.send).toHaveBeenCalledTimes(1);
    expect(decode(socket.sent[0])).toBe("ls -la\n");
  });

  it("writes incoming binary frames to the terminal (ws.onmessage -> term.write)", () => {
    const { term, socket } = setup();
    socket.emit(new TextEncoder().encode("hello pty").buffer);
    expect(term.written).toHaveLength(1);
    expect(decode(term.written[0])).toBe("hello pty");
  });

  it("ignores non-binary inbound frames so control echoes never corrupt the screen", () => {
    const { term, socket } = setup();
    socket.emit("not binary");
    expect(term.written).toHaveLength(0);
  });

  it("sends resize as a JSON text control frame", () => {
    const { socket, api } = setup();
    api.sendResize(120, 40);
    expect(socket.sent).toContain('{"type":"resize","cols":120,"rows":40}');
  });

  it("buffers output until the socket opens, then flushes in order", () => {
    const { term, socket, api } = setup(CONNECTING);
    term.type("a");
    api.sendResize(80, 24);
    expect(socket.send).not.toHaveBeenCalled();
    socket.open();
    expect(socket.send).toHaveBeenCalledTimes(2);
    expect(decode(socket.sent[0])).toBe("a");
    expect(socket.sent[1]).toBe('{"type":"resize","cols":80,"rows":24}');
  });

  it("disposes the data subscription and closes the socket on close()", () => {
    const { term, socket, api } = setup();
    api.close();
    expect(term.disposed).toBe(true);
    expect(socket.close).toHaveBeenCalledTimes(1);
  });

  it("reports open status once the socket connects", () => {
    const { socket, statuses } = setup(CONNECTING);
    expect(statuses).toEqual([]);
    socket.open();
    expect(statuses).toContainEqual({ status: "open", code: undefined });
  });

  it("reports closed status with the close code on an involuntary close", () => {
    const { socket, statuses } = setup();
    socket.emitClose(1008);
    expect(statuses).toContainEqual({ status: "closed", code: 1008 });
  });

  it("stays silent on a deliberate close() (handler detached)", () => {
    const { socket, api, statuses } = setup();
    api.close();
    socket.emitClose(1000);
    expect(statuses.some((entry) => entry.status === "closed")).toBe(false);
  });

  it("drops input typed after the socket closes (no InvalidStateError)", () => {
    const { term, socket } = setup();
    socket.emitClose(1006); // server/network dropped the connection

    expect(() => term.type("late keystroke")).not.toThrow();
    expect(socket.send).not.toHaveBeenCalled();
  });
});
