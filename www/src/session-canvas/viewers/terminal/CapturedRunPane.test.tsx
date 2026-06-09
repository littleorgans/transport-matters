import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CapturedRunPane } from "./CapturedRunPane";

// xterm renders to a real canvas/WebGL surface that jsdom cannot host, so the
// terminal is mocked (as in TerminalPane.test). The point under test is the
// captured-run wiring: the pane connects to the captured endpoint for its
// provider and turns a launch-error frame into a banner. The raw socket protocol
// is proven separately in terminalSocket.test.ts; the pane has no chrome of its
// own (its captured identity is the window title), so there is nothing else to assert.
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

describe("CapturedRunPane", () => {
  beforeEach(() => {
    terminals.length = 0;
    sockets.length = 0;
    vi.stubGlobal("WebSocket", MockWebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("connects to the claude captured endpoint for the claude provider", () => {
    render(<CapturedRunPane provider="claude" />);
    expect(only(sockets).url).toMatch(/\/api\/captured-runs\/claude\/terminal\?cols=80&rows=24$/);
  });

  it("connects to the codex captured endpoint for the codex provider", () => {
    render(<CapturedRunPane provider="codex" />);
    expect(only(sockets).url).toMatch(/\/api\/captured-runs\/codex\/terminal\?cols=80&rows=24$/);
  });

  it("turns a captured-run error frame into an alert banner", () => {
    render(<CapturedRunPane provider="claude" />);
    act(() =>
      only(sockets).emitText(
        JSON.stringify({ type: "captured-run.error", code: "launch_failed", message: "boom" }),
      ),
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/launch_failed/);
    expect(alert).toHaveTextContent(/boom/);
  });

  it("surfaces a refused state naming the provider when the socket is rejected (close 1008)", () => {
    render(<CapturedRunPane provider="codex" />);
    act(() => {
      only(sockets).onclose?.({ code: 1008, reason: "origin not allowed" });
    });
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/refused/i);
    expect(alert).toHaveTextContent(/Codex/);
  });

  it("does not write inbound control frames to the terminal screen", () => {
    render(<CapturedRunPane provider="claude" />);
    act(() => only(sockets).emitText(READY));
    expect(only(terminals).write).not.toHaveBeenCalled();
  });

  it("closes the socket and disposes the terminal on unmount", () => {
    const { unmount } = render(<CapturedRunPane provider="claude" />);
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
