import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TerminalPane } from "./TerminalPane";

// xterm renders to a real canvas/WebGL surface that jsdom cannot host, so the
// terminal is mocked. The point under test is the wiring: a Terminal is opened,
// a socket is attached, and both are torn down on unmount. The raw protocol
// (onData/onmessage/resize) is proven separately in terminalSocket.test.ts.
// vi.mock factories are hoisted above the file, so the mocked classes live in a
// vi.hoisted block that the factories and the assertions both read from.
const { terminals, MockTerminal, MockFitAddon } = vi.hoisted(() => {
  class MockTerminal {
    cols = 80;
    rows = 24;
    selection = "";
    loadAddon = vi.fn();
    open = vi.fn();
    focus = vi.fn();
    write = vi.fn();
    dispose = vi.fn();
    onData = vi.fn(() => ({ dispose: vi.fn() }));
    onSelectionChange = vi.fn((_listener: () => void) => ({ dispose: vi.fn() }));
    hasSelection = vi.fn(() => this.selection.length > 0);
    getSelection = vi.fn(() => this.selection);
    constructor() {
      terminals.push(this);
    }
  }
  class MockFitAddon {
    activate = vi.fn();
    dispose = vi.fn();
    fit = vi.fn();
  }
  const terminals: MockTerminal[] = [];
  return { terminals, MockTerminal, MockFitAddon };
});

vi.mock("@xterm/xterm", () => ({ Terminal: MockTerminal }));
vi.mock("@xterm/addon-fit", () => ({ FitAddon: MockFitAddon }));

const sockets: MockWebSocket[] = [];
class MockWebSocket {
  static readonly OPEN = 1;
  binaryType = "blob";
  readyState = MockWebSocket.OPEN;
  onopen: ((event: unknown) => void) | null = null;
  onmessage: ((event: unknown) => void) | null = null;
  onclose: ((event: unknown) => void) | null = null;
  send = vi.fn();
  close = vi.fn();
  constructor(readonly url: string) {
    sockets.push(this);
  }
}

describe("TerminalPane", () => {
  beforeEach(() => {
    terminals.length = 0;
    sockets.length = 0;
    vi.stubGlobal("WebSocket", MockWebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("opens an xterm terminal and a same-origin terminal websocket", () => {
    render(<TerminalPane />);

    const terminal = only(terminals);
    const socket = only(sockets);
    expect(terminal.loadAddon).toHaveBeenCalledTimes(1);
    expect(terminal.open).toHaveBeenCalledTimes(1);
    expect(socket.url).toMatch(/\/api\/terminal\?cols=80&rows=24$/);
  });

  it("focuses the terminal on mount so keys (incl. Ctrl-C) reach the PTY", () => {
    render(<TerminalPane />);
    expect(only(terminals).focus).toHaveBeenCalledTimes(1);
  });

  it("surfaces a refused state when the socket is rejected (close 1008)", () => {
    render(<TerminalPane />);
    const socket = only(sockets);

    act(() => {
      socket.onclose?.({ code: 1008, reason: "origin not allowed" });
    });

    expect(screen.getByRole("alert")).toHaveTextContent(/refused/i);
  });

  it("copies the selection to the clipboard as it changes (copy-on-select)", () => {
    const writeText = vi.fn(() => Promise.resolve());
    vi.stubGlobal("navigator", { ...window.navigator, clipboard: { writeText } });
    render(<TerminalPane />);
    const terminal = only(terminals);
    const [onSelectionChange] = terminal.onSelectionChange.mock.calls[0] ?? [];
    if (onSelectionChange === undefined) throw new Error("expected a selection listener");

    terminal.selection = "picked text";
    onSelectionChange();
    expect(writeText).toHaveBeenCalledWith("picked text");

    // Clearing the selection must not clobber the clipboard with "".
    terminal.selection = "";
    onSelectionChange();
    expect(writeText).toHaveBeenCalledTimes(1);
  });

  it("sends an initial resize control frame sized to the terminal", () => {
    render(<TerminalPane />);

    expect(only(sockets).send).toHaveBeenCalledWith('{"type":"resize","cols":80,"rows":24}');
  });

  it("closes the socket and disposes the terminal on unmount", () => {
    const { unmount } = render(<TerminalPane />);
    const terminal = only(terminals);
    const socket = only(sockets);

    unmount();

    expect(socket.close).toHaveBeenCalledTimes(1);
    expect(terminal.dispose).toHaveBeenCalledTimes(1);
  });
});

/** Assert exactly one instance was created and return it (narrows away undefined). */
function only<T>(items: readonly T[]): T {
  expect(items).toHaveLength(1);
  const [item] = items;
  if (item === undefined) throw new Error("expected exactly one item");
  return item;
}
