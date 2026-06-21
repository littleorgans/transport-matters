import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetCapturedRunStoreForTests, useCapturedRunStore } from "../../model/capturedRunStore";
import { CapturedRunPane } from "./CapturedRunPane";
import { resolvePasteHandle } from "./pasteRegistry";

// xterm renders to a real canvas/WebGL surface that jsdom cannot host, so the
// terminal is mocked (as in TerminalPane.test). The point under test is the
// managed-run lifecycle: the pane spawns a run via POST /v1/runs (or re-attaches
// a persisted run id), attaches its terminal WebSocket to /v1/runs/{id}/terminal,
// and turns a spawn failure or run.error frame into a banner. The raw socket
// protocol is proven separately in terminalSocket.test.ts.
const { terminals, MockTerminal, MockFitAddon } = vi.hoisted(() => {
  class MockTerminal {
    cols = 80;
    rows = 24;
    parser = { registerOscHandler: vi.fn() };
    loadAddon = vi.fn();
    open = vi.fn();
    focus = vi.fn();
    paste = vi.fn();
    write = vi.fn();
    dispose = vi.fn();
    onData = vi.fn(() => ({ dispose: vi.fn() }));
    onSelectionChange = vi.fn(() => ({ dispose: vi.fn() }));
    hasSelection = vi.fn(() => false);
    getSelection = vi.fn(() => "");
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

const { createCapturedRunMock, terminateRunMock } = vi.hoisted(() => ({
  createCapturedRunMock: vi.fn(),
  terminateRunMock: vi.fn(),
}));

vi.mock("@xterm/xterm", () => ({ Terminal: MockTerminal }));
vi.mock("@xterm/addon-fit", () => ({ FitAddon: MockFitAddon }));
vi.mock("../../../api", () => ({
  createCapturedRun: createCapturedRunMock,
  terminateRun: terminateRunMock,
}));

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
  emitBinary(data = new Uint8Array([65]).buffer): void {
    this.onmessage?.({ data });
  }
}

describe("CapturedRunPane", () => {
  beforeEach(() => {
    terminals.length = 0;
    sockets.length = 0;
    localStorage.clear();
    resetCapturedRunStoreForTests();
    createCapturedRunMock.mockReset();
    terminateRunMock.mockReset();
    vi.stubGlobal("WebSocket", MockWebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("spawns a run via POST then attaches its terminal socket", async () => {
    createCapturedRunMock.mockResolvedValue("run-abc123");

    render(<CapturedRunPane runKey="claude:k1" provider="claude" worktreeId="wt-1" />);

    await waitFor(() => expect(sockets).toHaveLength(1));
    expect(createCapturedRunMock).toHaveBeenCalledWith("claude", "wt-1", true, undefined, false);
    expect(only(sockets).url).toMatch(/\/v1\/runs\/run-abc123\/terminal\?cols=80&rows=24$/);
  });

  it("shows an initializing indicator until first terminal output", async () => {
    createCapturedRunMock.mockResolvedValue("run-abc123");

    render(<CapturedRunPane runKey="claude:k1" provider="claude" worktreeId="wt-1" />);

    await waitFor(() => expect(sockets).toHaveLength(1));
    expect(screen.getByRole("status")).toHaveTextContent(/Starting Claude/);
    act(() => only(sockets).emitBinary());
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
  });

  it("uses the core OSC color replies toggle at spawn time", async () => {
    createCapturedRunMock.mockResolvedValue("run-abc123");
    useCapturedRunStore.getState().setOscColorReplies(false);

    render(<CapturedRunPane runKey="claude:k1" provider="claude" worktreeId="wt-1" />);

    await waitFor(() => expect(sockets).toHaveLength(1));
    expect(createCapturedRunMock).toHaveBeenCalledWith("claude", "wt-1", false, undefined, false);
  });

  it("re-attaches a persisted run id without spawning a new run", async () => {
    useCapturedRunStore.setState({
      runs: { "codex:k1": { provider: "codex", runId: "run-persisted" } },
    });

    render(<CapturedRunPane runKey="codex:k1" provider="codex" worktreeId="wt-1" />);

    await waitFor(() => expect(sockets).toHaveLength(1));
    expect(createCapturedRunMock).not.toHaveBeenCalled();
    expect(only(sockets).url).toMatch(/\/v1\/runs\/run-persisted\/terminal\?cols=80&rows=24$/);
  });

  it("registers a paste handle for its pane id and deregisters on unmount", async () => {
    createCapturedRunMock.mockResolvedValue("run-abc123");
    const { unmount } = render(
      <CapturedRunPane runKey="claude:k1" provider="claude" worktreeId="wt-1" />,
    );

    await waitFor(() => expect(sockets).toHaveLength(1));
    const terminal = only(terminals);
    const handle = resolvePasteHandle("claude:k1");
    expect(handle).not.toBeNull();
    handle?.("hello");
    expect(terminal.paste).toHaveBeenCalledWith("hello");
    unmount();
    expect(resolvePasteHandle("claude:k1")).toBeNull();
  });

  it("turns a run.error frame into an alert banner", async () => {
    createCapturedRunMock.mockResolvedValue("run-abc123");
    render(<CapturedRunPane runKey="claude:k1" provider="claude" worktreeId="wt-1" />);
    await waitFor(() => expect(sockets).toHaveLength(1));

    act(() =>
      only(sockets).emitText(
        JSON.stringify({ type: "run.error", code: "run_not_attachable", message: "gone" }),
      ),
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/run_not_attachable/);
    expect(alert).toHaveTextContent(/gone/);
  });

  it("surfaces a refused state naming the provider when the socket is rejected (close 1008)", async () => {
    createCapturedRunMock.mockResolvedValue("run-abc123");
    render(<CapturedRunPane runKey="codex:k1" provider="codex" worktreeId="wt-1" />);
    await waitFor(() => expect(sockets).toHaveLength(1));

    act(() => {
      only(sockets).onclose?.({ code: 1008, reason: "origin not allowed" });
    });

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/refused/i);
    expect(alert).toHaveTextContent(/Codex/);
  });

  it("shows a spawn-failure banner when POST /v1/runs fails", async () => {
    createCapturedRunMock.mockRejectedValue(new Error("no claude on PATH"));

    render(<CapturedRunPane runKey="claude:k1" provider="claude" worktreeId="wt-1" />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/Claude/);
    expect(alert).toHaveTextContent(/no claude on PATH/);
    expect(sockets).toHaveLength(0);
  });

  it("closes the socket and disposes the terminal on unmount", async () => {
    createCapturedRunMock.mockResolvedValue("run-abc123");
    const { unmount } = render(
      <CapturedRunPane runKey="claude:k1" provider="claude" worktreeId="wt-1" />,
    );
    await waitFor(() => expect(sockets).toHaveLength(1));

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
