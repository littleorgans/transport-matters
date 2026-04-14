import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../../api";
import { useUIStore } from "../../stores/uiStore";
import type { InternalRequest, PausedFlow } from "../../types";
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
}));

const mockIr: InternalRequest = {
  model: "claude-3",
  provider: "anthropic",
  system: [],
  tools: [],
  messages: [],
  sampling: { max_tokens: 1024, temperature: null, top_p: null, top_k: null, stop_sequences: [] },
  metadata: { session_id: null, device_id: null, account_id: null, provider_metadata: {} },
  stream: false,
  provider_extras: {},
};

const mockPausedFlow: PausedFlow = {
  flow_id: "flow-abc123",
  ir: mockIr,
  original_tools: mockIr.tools,
  original_system: mockIr.system,
  original_messages: mockIr.messages,
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
      queryKey: ["exchange", mockPausedFlow.flow_id],
    });
  });
});

describe("BreakpointEditor — forwarding timeout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    useUIStore.setState({ forwardingFlowId: null, pausedFlow: null });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows timeout error after 45 seconds of forwarding", () => {
    const { wrapper } = makeWrapper();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={vi.fn()} />, { wrapper });

    act(() => {
      useUIStore.setState({ forwardingFlowId: "flow-abc123" });
    });

    act(() => {
      vi.advanceTimersByTime(45_000);
    });

    expect(screen.getByText(/Forward timed out/)).toBeInTheDocument();
    expect(useUIStore.getState().forwardingFlowId).toBeNull();
  });

  it("cancels timeout when forwarding completes before 45 seconds", () => {
    const { wrapper } = makeWrapper();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={vi.fn()} />, { wrapper });

    act(() => {
      useUIStore.setState({ forwardingFlowId: "flow-abc123" });
    });

    act(() => {
      useUIStore.setState({ forwardingFlowId: null });
    });

    act(() => {
      vi.advanceTimersByTime(45_000);
    });

    expect(screen.queryByText(/Forward timed out/)).toBeNull();
  });
});
