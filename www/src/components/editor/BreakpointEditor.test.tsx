import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../../api";
import { exchangeKey } from "../../lib/queryKeys";
import { useOverlaysStore } from "../../stores/overlaysStore";
import { useUIStore } from "../../stores/uiStore";
import type { InternalRequest, Override, PausedFlow } from "../../types";
import { BreakpointEditor } from "./BreakpointEditor";

vi.mock("../../api", () => ({
  releaseFlow: vi.fn().mockResolvedValue(undefined),
  releaseFlowUnmodified: vi.fn().mockResolvedValue(undefined),
  dropFlow: vi.fn().mockResolvedValue(undefined),
  reauditFlow: vi.fn().mockResolvedValue({ audit: null, curated_ir: {}, tokens_before: null }),
  fetchOverrides: vi.fn().mockResolvedValue({ overrides: [], enabled: true }),
  patchOverrides: vi
    .fn()
    .mockResolvedValue({ overrides: [], enabled: true, audit: null, curated_ir: null }),
  clearOverrides: vi.fn().mockResolvedValue(undefined),
  toggleOverrides: vi.fn().mockResolvedValue({ enabled: true, audit: null, curated_ir: null }),
  // BreakpointEditor pulls fetchMeta through useMeta to decide the
  // cwd it stamps on a SAVE AS OVERLAY draft. The mock must expose
  // it or the query throws when the editor mounts.
  fetchMeta: vi.fn().mockResolvedValue({ cwd: "/tmp/test", workspaceId: "test/abc12345" }),
}));

const mockIr: InternalRequest = {
  model: "claude-3",
  provider: "anthropic",
  system: [{ type: "text", text: "You are helpful." }],
  tools: [{ name: "Read", description: "read files", input_schema: { type: "object" } }],
  messages: [{ role: "user", content: [{ type: "text", text: "hi" }] }],
  sampling: { max_tokens: 1024, temperature: null, top_p: null, top_k: null, stop_sequences: [] },
  metadata: { session_id: null, device_id: null, account_id: null, provider_metadata: {} },
  stream: false,
  provider_extras: {},
};

const mockPausedFlow: PausedFlow = {
  flow_id: "flow-abc123",
  transport: "http",
  provisional_exchange_id: null,
  run_id: "run-1",
  track_id: "agent-1",
  parent_track_id: "run-1",
  track_display_name: "backend-engineer",
  track_role: "subagent",
  ir: mockIr,
  original_tools: mockIr.tools,
  original_system: mockIr.system,
  original_messages: mockIr.messages,
  original_sampling: mockIr.sampling,
  original_provider_extras: mockIr.provider_extras,
  audit: null,
  paused_at_ms: Date.now() - 5000,
  tokens_before: null,
};

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return {
    qc,
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    ),
  };
}

describe("BreakpointEditor — forward path (waits for SSE)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useUIStore.setState({ forwardingFlowId: null, pausedFlow: null });
  });

  it("Forward: calls releaseFlow and sets forwardingFlowId (does not call onResolved)", async () => {
    const { wrapper } = makeWrapper();
    const { releaseFlow } = await import("../../api");
    const onResolved = vi.fn();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={onResolved} />, { wrapper });

    fireEvent.click(screen.getByRole("button", { name: "Forward" }));

    await waitFor(() =>
      expect(releaseFlow).toHaveBeenCalledWith(
        "flow-abc123",
        expect.objectContaining({ model: "claude-3" }),
      ),
    );
    expect(onResolved).not.toHaveBeenCalled();
    expect(useUIStore.getState().forwardingFlowId).toBe("flow-abc123");
  });

  it("Pass Through: calls releaseFlowUnmodified and sets forwardingFlowId", async () => {
    const { wrapper } = makeWrapper();
    const { releaseFlowUnmodified } = await import("../../api");
    const onResolved = vi.fn();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={onResolved} />, { wrapper });

    fireEvent.click(screen.getByRole("button", { name: "Pass Through" }));

    await waitFor(() => expect(releaseFlowUnmodified).toHaveBeenCalledWith("flow-abc123"));
    expect(onResolved).not.toHaveBeenCalled();
    expect(useUIStore.getState().forwardingFlowId).toBe("flow-abc123");
  });

  it("Codex websocket forward resolves immediately without waiting for SSE", async () => {
    const { wrapper } = makeWrapper();
    const onResolved = vi.fn();
    render(
      <BreakpointEditor
        pausedFlow={{
          ...mockPausedFlow,
          transport: "websocket",
          provisional_exchange_id: "exchange-provisional-1",
          ir: { ...mockIr, provider: "codex" },
        }}
        onResolved={onResolved}
      />,
      { wrapper },
    );

    fireEvent.click(screen.getByRole("button", { name: "Forward" }));

    await waitFor(() => expect(api.releaseFlow).toHaveBeenCalled());
    await waitFor(() => expect(onResolved).toHaveBeenCalledTimes(1));
    expect(useUIStore.getState().selectedId).toBe("exchange-provisional-1");
    expect(useUIStore.getState().forwardingFlowId).toBeNull();
  });

  it("Codex websocket pass through selects the provisional exchange before closing", async () => {
    const { wrapper } = makeWrapper();
    const onResolved = vi.fn();
    render(
      <BreakpointEditor
        pausedFlow={{
          ...mockPausedFlow,
          transport: "websocket",
          provisional_exchange_id: "exchange-provisional-2",
          ir: { ...mockIr, provider: "codex" },
        }}
        onResolved={onResolved}
      />,
      { wrapper },
    );

    fireEvent.click(screen.getByRole("button", { name: "Pass Through" }));

    await waitFor(() => expect(api.releaseFlowUnmodified).toHaveBeenCalled());
    await waitFor(() => expect(onResolved).toHaveBeenCalledTimes(1));
    expect(useUIStore.getState().selectedId).toBe("exchange-provisional-2");
    expect(useUIStore.getState().forwardingFlowId).toBeNull();
  });
});

describe("BreakpointEditor — drop path (immediate close)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useUIStore.setState({ forwardingFlowId: null, pausedFlow: null });
  });

  it("Drop: calls dropFlow then onResolved immediately", async () => {
    const { wrapper } = makeWrapper();
    const { dropFlow } = await import("../../api");
    const onResolved = vi.fn();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={onResolved} />, { wrapper });

    fireEvent.click(screen.getByRole("button", { name: "Drop" }));

    await waitFor(() => expect(dropFlow).toHaveBeenCalledWith("flow-abc123"));
    await waitFor(() => expect(onResolved).toHaveBeenCalledTimes(1));
  });
});

describe("BreakpointEditor — error path", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useUIStore.setState({ forwardingFlowId: null, pausedFlow: null });
  });

  it("Forward failure: shows error banner, does not set forwardingFlowId", async () => {
    const { wrapper } = makeWrapper();
    vi.mocked(api.releaseFlow).mockRejectedValueOnce(new Error("Network error"));
    const onResolved = vi.fn();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={onResolved} />, { wrapper });

    fireEvent.click(screen.getByRole("button", { name: "Forward" }));

    await waitFor(() => expect(screen.getByText("Network error")).toBeTruthy());
    expect(onResolved).not.toHaveBeenCalled();
    expect(useUIStore.getState().forwardingFlowId).toBeNull();
  });

  it("Drop failure: shows error banner, does not call onResolved", async () => {
    const { wrapper } = makeWrapper();
    vi.mocked(api.dropFlow).mockRejectedValueOnce(new Error("Drop failed"));
    const onResolved = vi.fn();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={onResolved} />, { wrapper });

    fireEvent.click(screen.getByRole("button", { name: "Drop" }));

    await waitFor(() => expect(screen.getByText("Drop failed")).toBeTruthy());
    expect(onResolved).not.toHaveBeenCalled();
  });

  it("Pass Through failure: shows error banner, does not set forwardingFlowId", async () => {
    const { wrapper } = makeWrapper();
    vi.mocked(api.releaseFlowUnmodified).mockRejectedValueOnce(new Error("Timeout"));
    const onResolved = vi.fn();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={onResolved} />, { wrapper });

    fireEvent.click(screen.getByRole("button", { name: "Pass Through" }));

    await waitFor(() => expect(screen.getByText("Timeout")).toBeTruthy());
    expect(onResolved).not.toHaveBeenCalled();
    expect(useUIStore.getState().forwardingFlowId).toBeNull();
  });

  it("error clears on subsequent attempt", async () => {
    const { wrapper } = makeWrapper();
    vi.mocked(api.dropFlow)
      .mockRejectedValueOnce(new Error("first failure"))
      .mockResolvedValueOnce(undefined);
    const onResolved = vi.fn();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={onResolved} />, { wrapper });

    fireEvent.click(screen.getByRole("button", { name: "Drop" }));
    await waitFor(() => expect(screen.getByText("first failure")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "Drop" }));
    await waitFor(() => expect(onResolved).toHaveBeenCalledTimes(1));
    expect(screen.queryByText("first failure")).toBeNull();
  });
});

describe("BreakpointEditor — cache invalidation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useUIStore.setState({ forwardingFlowId: null, pausedFlow: null });
  });

  it("Forward: invalidates exchange detail cache before setting forwardingFlowId", async () => {
    const { qc, wrapper } = makeWrapper();
    const invalidateSpy = vi.spyOn(qc, "invalidateQueries");
    const onResolved = vi.fn();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={onResolved} />, { wrapper });

    fireEvent.click(screen.getByRole("button", { name: "Forward" }));

    await waitFor(() => expect(useUIStore.getState().forwardingFlowId).toBe("flow-abc123"));
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: exchangeKey(mockPausedFlow.flow_id),
    });
  });

  it("Codex websocket forward invalidates the provisional exchange detail cache", async () => {
    const { qc, wrapper } = makeWrapper();
    const invalidateSpy = vi.spyOn(qc, "invalidateQueries");
    render(
      <BreakpointEditor
        pausedFlow={{
          ...mockPausedFlow,
          transport: "websocket",
          provisional_exchange_id: "exchange-provisional-3",
          ir: { ...mockIr, provider: "codex" },
        }}
        onResolved={vi.fn()}
      />,
      { wrapper },
    );

    fireEvent.click(screen.getByRole("button", { name: "Forward" }));

    await waitFor(() => expect(api.releaseFlow).toHaveBeenCalled());
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: exchangeKey("exchange-provisional-3"),
    });
  });
});

describe("BreakpointEditor — forwarding timeout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    useUIStore.setState({
      forwardingFlowId: null,
      forwardingLastActivityAt: null,
      pausedFlow: null,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows timeout error after 120 seconds of upstream silence", () => {
    const { wrapper } = makeWrapper();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={vi.fn()} />, { wrapper });

    act(() => {
      useUIStore.setState({ forwardingFlowId: "flow-abc123" });
    });

    act(() => {
      vi.advanceTimersByTime(120_000);
    });

    expect(screen.getByText(/Forward timed out/)).toBeInTheDocument();
    expect(useUIStore.getState().forwardingFlowId).toBeNull();
  });

  it("does not fire before 120 seconds", () => {
    const { wrapper } = makeWrapper();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={vi.fn()} />, { wrapper });

    act(() => {
      useUIStore.setState({ forwardingFlowId: "flow-abc123" });
    });

    act(() => {
      vi.advanceTimersByTime(119_000);
    });

    expect(screen.queryByText(/Forward timed out/)).toBeNull();
    expect(useUIStore.getState().forwardingFlowId).toBe("flow-abc123");
  });

  it("cancels timeout when forwarding completes before 120 seconds", () => {
    const { wrapper } = makeWrapper();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={vi.fn()} />, { wrapper });

    act(() => {
      useUIStore.setState({ forwardingFlowId: "flow-abc123" });
    });

    act(() => {
      useUIStore.getState().setForwardingFlowId(null);
    });

    act(() => {
      vi.advanceTimersByTime(120_000);
    });

    expect(screen.queryByText(/Forward timed out/)).toBeNull();
  });

  it("restarts the 120s window when an activity event lands mid-wait", () => {
    const { wrapper } = makeWrapper();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={vi.fn()} />, { wrapper });

    act(() => {
      useUIStore.setState({ forwardingFlowId: "flow-abc123" });
    });

    // 60s of upstream silence pass ...
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    // ... then an SSE event for this flow stamps activity. The effect
    // re-runs with the new lastActivityAt dep and starts a fresh 120s
    // timer from this moment.
    act(() => {
      useUIStore.getState().bumpForwardingActivity();
    });

    // Original cutoff (120s from t=0) elapses — banner must not fire,
    // because the window restarted at t=60s.
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(screen.queryByText(/Forward timed out/)).toBeNull();
    expect(useUIStore.getState().forwardingFlowId).toBe("flow-abc123");

    // Crossing the new cutoff (t=60s + 120s = t=180s) finally fires it.
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(screen.getByText(/Forward timed out/)).toBeInTheDocument();
  });
});

// ── Tab restructure: MESSAGES | OVERLAY | RAW ─────────────────────
// The editor now exposes three semantic tabs. MESSAGES shows the
// per-call payload (global toggles + message stream), OVERLAY shows
// the durable session shape (sampling + system + tools) and hosts
// the SAVE AS OVERLAY affordance, RAW dumps the edited IR as JSON.
// These tests lock the tab taxonomy and the section/button wiring.

/**
 * Seed the React Query cache with a populated overrides response so
 * the SAVE AS OVERLAY button renders enabled. Mirrors the shape the
 * real `fetchOverrides` returns so there's no mock drift.
 */
function seedOverrides(qc: QueryClient, overrides: Override[]) {
  qc.setQueryData(["overrides", "run-1", "agent-1"], { overrides, enabled: true });
}

describe("BreakpointEditor — tab restructure", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useUIStore.setState({
      forwardingFlowId: null,
      pausedFlow: null,
      activeRoute: "intercept",
    });
    useOverlaysStore.setState({ overlays: [], draftId: null });
  });

  it("renders MESSAGES, OVERLAY, RAW tabs and lands on MESSAGES by default", async () => {
    const { wrapper } = makeWrapper();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={vi.fn()} />, { wrapper });

    const messagesTab = screen.getByRole("button", { name: "messages" });
    const overlayTab = screen.getByRole("button", { name: "overlay" });
    const rawTab = screen.getByRole("button", { name: "raw" });
    expect(messagesTab).toBeInTheDocument();
    expect(overlayTab).toBeInTheDocument();
    expect(rawTab).toBeInTheDocument();
    // Default landing: pressed state on MESSAGES.
    expect(messagesTab.className).toMatch(/tab-pressed/);
    expect(overlayTab.className).not.toMatch(/tab-pressed/);
    expect(rawTab.className).not.toMatch(/tab-pressed/);
  });

  it("loads overrides for the paused track scope", async () => {
    const { wrapper } = makeWrapper();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={vi.fn()} />, { wrapper });

    await waitFor(() =>
      expect(api.fetchOverrides).toHaveBeenCalledWith({
        run_id: "run-1",
        track_id: "agent-1",
      }),
    );
  });

  it("MESSAGES tab shows Global + Messages sections and hides Sampling", () => {
    const { wrapper } = makeWrapper();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={vi.fn()} />, { wrapper });

    expect(screen.getByText("Global")).toBeInTheDocument();
    expect(screen.getByText(/Messages\s*·/)).toBeInTheDocument();
    expect(screen.queryByText("Sampling")).toBeNull();
    // SAVE AS OVERLAY only lives inside the OVERLAY tab now.
    expect(screen.queryByRole("button", { name: /save as overlay/i })).toBeNull();
  });

  it("OVERLAY tab shows Sampling/System/Tools and hides MESSAGES sections", () => {
    const { wrapper } = makeWrapper();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={vi.fn()} />, { wrapper });

    fireEvent.click(screen.getByRole("button", { name: "overlay" }));

    expect(screen.getByText("Sampling")).toBeInTheDocument();
    expect(screen.getByText(/Tools\s*·/)).toBeInTheDocument();
    expect(screen.queryByText("Global")).toBeNull();
    expect(screen.queryByText(/Messages\s*·/)).toBeNull();
  });

  it("RAW tab hides both MESSAGES and OVERLAY section content", () => {
    const { wrapper } = makeWrapper();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={vi.fn()} />, { wrapper });

    fireEvent.click(screen.getByRole("button", { name: "raw" }));

    expect(screen.queryByText("Global")).toBeNull();
    expect(screen.queryByText(/Messages\s*·/)).toBeNull();
    expect(screen.queryByText("Sampling")).toBeNull();
    expect(screen.queryByRole("button", { name: /save as overlay/i })).toBeNull();
  });
});

describe("BreakpointEditor — SAVE AS OVERLAY in tab bar right slot", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useUIStore.setState({
      forwardingFlowId: null,
      pausedFlow: null,
      activeRoute: "intercept",
    });
    useOverlaysStore.setState({ overlays: [], draftId: null });
  });

  it("is absent on MESSAGES (default landing)", () => {
    const { wrapper } = makeWrapper();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={vi.fn()} />, { wrapper });

    expect(screen.queryByRole("button", { name: /save as overlay/i })).toBeNull();
  });

  it("is absent on RAW", () => {
    const { wrapper } = makeWrapper();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={vi.fn()} />, { wrapper });

    fireEvent.click(screen.getByRole("button", { name: "raw" }));

    expect(screen.queryByRole("button", { name: /save as overlay/i })).toBeNull();
  });

  it("renders disabled on OVERLAY with 'make an override' phrase when none stored", () => {
    const { wrapper } = makeWrapper();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={vi.fn()} />, { wrapper });

    fireEvent.click(screen.getByRole("button", { name: "overlay" }));

    const button = screen.getByRole("button", { name: /save as overlay/i });
    expect(button).toBeInTheDocument();
    expect(button).toBeDisabled();
    expect(screen.getByText("Make an override to save as an overlay")).toBeInTheDocument();
  });

  it("renders enabled on OVERLAY with pluralized 'ready to lift' phrase when overrides exist", () => {
    const { qc, wrapper } = makeWrapper();
    seedOverrides(qc, [
      { kind: "tool_toggle", target: "tool:Read", value: false },
      { kind: "tool_toggle", target: "tool:Write", value: false },
    ]);

    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={vi.fn()} />, { wrapper });

    fireEvent.click(screen.getByRole("button", { name: "overlay" }));

    expect(screen.getByText("2 overrides ready to lift")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save as overlay/i })).not.toBeDisabled();
  });

  it("renders singular 'override ready to lift' for a single stored override", () => {
    const { qc, wrapper } = makeWrapper();
    seedOverrides(qc, [{ kind: "tool_toggle", target: "tool:Read", value: false }]);

    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={vi.fn()} />, { wrapper });

    fireEvent.click(screen.getByRole("button", { name: "overlay" }));

    expect(screen.getByText("1 override ready to lift")).toBeInTheDocument();
  });

  it("hides the helper phrase on MESSAGES and RAW", () => {
    const { qc, wrapper } = makeWrapper();
    seedOverrides(qc, [{ kind: "tool_toggle", target: "tool:Read", value: false }]);

    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={vi.fn()} />, { wrapper });

    // MESSAGES (default landing)
    expect(screen.queryByText(/ready to lift|make an override/i)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "raw" }));
    expect(screen.queryByText(/ready to lift|make an override/i)).toBeNull();
  });

  it("creates a project-scoped draft and switches to the overlays route on click", () => {
    const { qc, wrapper } = makeWrapper();
    const toolToggle: Override = { kind: "tool_toggle", target: "tool:Read", value: false };
    seedOverrides(qc, [toolToggle]);
    // Seed meta directly so `handleSaveAsOverlay` stamps the fetched
    // cwd instead of the UNKNOWN_CWD cold-click fallback. Mirrors the
    // real app's main.tsx prefetch path.
    qc.setQueryData(["meta"], { cwd: "/tmp/test", workspaceId: "test/abc12345" });

    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={vi.fn()} />, { wrapper });

    fireEvent.click(screen.getByRole("button", { name: "overlay" }));

    const button = screen.getByRole("button", { name: /save as overlay/i });
    expect(button).not.toBeDisabled();
    fireEvent.click(button);

    const store = useOverlaysStore.getState();
    expect(store.overlays).toHaveLength(1);
    const draft = store.overlays[0];
    expect(draft?.draft).toBe(true);
    expect(draft?.overrides).toEqual([toolToggle]);
    expect(draft?.scope).toEqual({ kind: "project", cwd: "/tmp/test" });
    expect(store.draftId).toBe(draft?.id);

    // Route hands off to the OVERLAYS lens so the user lands on their
    // new draft immediately.
    expect(useUIStore.getState().activeRoute).toBe("overlays");
  });
});
