import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CapturedClaudePane } from "./CapturedClaudePane";

// xterm renders to a real canvas/WebGL surface that jsdom cannot host, so the
// terminal is mocked (as in TerminalPane.test). The point under test is the
// captured-run wiring: the pane connects to the captured endpoint, surfaces the
// ready frame's run id, and turns an error frame into a banner. The raw socket
// protocol is proven separately in terminalSocket.test.ts.
const { terminals, MockTerminal, MockFitAddon } = vi.hoisted(() => {
  class MockTerminal {
    cols = 80;
    rows = 24;
    loadAddon = vi.fn();
    open = vi.fn();
    focus = vi.fn();
    write = vi.fn();
    dispose = vi.fn();
    onData = vi.fn(() => ({ dispose: vi.fn() }));
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
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: unknown) => void) | null = null;
  send = vi.fn();
  close = vi.fn();
  constructor(readonly url: string) {
    sockets.push(this);
  }
  emitText(text: string): void {
    this.onmessage?.({ data: text });
  }
}

const READY = JSON.stringify({
  type: "captured-run.ready",
  runId: "run-abc123def",
  cwd: "/work/proj",
  storageDir: "/store",
  proxyPort: 51234,
  webPort: 7999,
  cli: "claude",
});

describe("CapturedClaudePane", () => {
  beforeEach(() => {
    terminals.length = 0;
    sockets.length = 0;
    vi.stubGlobal("WebSocket", MockWebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("connects to the captured Claude terminal endpoint, not the bare terminal", () => {
    render(<CapturedClaudePane />);
    expect(only(sockets).url).toMatch(/\/api\/captured-runs\/claude\/terminal\?cols=80&rows=24$/);
  });

  it("marks the pane as a captured run before the ready frame lands", () => {
    render(<CapturedClaudePane />);
    expect(screen.getByText("captured")).toBeInTheDocument();
    expect(screen.getByText(/starting captured claude/i)).toBeInTheDocument();
  });

  it("surfaces the run id once the ready frame arrives", () => {
    render(<CapturedClaudePane />);
    act(() => only(sockets).emitText(READY));
    expect(screen.getByText(/run run-abc1/)).toBeInTheDocument();
  });

  it("turns a captured-run error frame into an alert banner", () => {
    render(<CapturedClaudePane />);
    act(() =>
      only(sockets).emitText(
        JSON.stringify({ type: "captured-run.error", code: "launch_failed", message: "boom" }),
      ),
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/launch_failed/);
    expect(alert).toHaveTextContent(/boom/);
  });

  it("surfaces a refused state when the socket is rejected (close 1008)", () => {
    render(<CapturedClaudePane />);
    act(() => {
      only(sockets).onclose?.({ code: 1008, reason: "origin not allowed" });
    });
    expect(screen.getByRole("alert")).toHaveTextContent(/refused/i);
  });

  it("does not write inbound control frames to the terminal screen", () => {
    render(<CapturedClaudePane />);
    act(() => only(sockets).emitText(READY));
    expect(only(terminals).write).not.toHaveBeenCalled();
  });

  it("closes the socket and disposes the terminal on unmount", () => {
    const { unmount } = render(<CapturedClaudePane />);
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
