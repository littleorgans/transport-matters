import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../../api";
import type { InternalRequest, PausedFlow } from "../../types";
import { BreakpointEditor } from "./BreakpointEditor";

vi.mock("../../api", () => ({
  releaseFlow: vi.fn().mockResolvedValue(undefined),
  releaseFlowUnmodified: vi.fn().mockResolvedValue(undefined),
  dropFlow: vi.fn().mockResolvedValue(undefined),
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
  audit: null,
  paused_at_ms: Date.now() - 5000,
};

describe("BreakpointEditor — onResolved path", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("Forward: calls releaseFlow then onResolved — no SSE needed", async () => {
    const { releaseFlow } = await import("../../api");
    const onResolved = vi.fn();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={onResolved} />);

    fireEvent.click(screen.getByRole("button", { name: "Forward" }));

    await waitFor(() =>
      expect(releaseFlow).toHaveBeenCalledWith(
        "flow-abc123",
        expect.objectContaining({ model: "claude-3" }),
      ),
    );
    await waitFor(() => expect(onResolved).toHaveBeenCalledTimes(1));
  });

  it("Drop: calls dropFlow then onResolved — no SSE needed", async () => {
    const { dropFlow } = await import("../../api");
    const onResolved = vi.fn();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={onResolved} />);

    fireEvent.click(screen.getByRole("button", { name: "Drop" }));

    await waitFor(() => expect(dropFlow).toHaveBeenCalledWith("flow-abc123"));
    await waitFor(() => expect(onResolved).toHaveBeenCalledTimes(1));
  });

  it("Pass Through: calls releaseFlowUnmodified then onResolved — no SSE needed", async () => {
    const { releaseFlowUnmodified } = await import("../../api");
    const onResolved = vi.fn();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={onResolved} />);

    fireEvent.click(screen.getByRole("button", { name: "Pass Through" }));

    await waitFor(() => expect(releaseFlowUnmodified).toHaveBeenCalledWith("flow-abc123"));
    await waitFor(() => expect(onResolved).toHaveBeenCalledTimes(1));
  });
});

describe("BreakpointEditor — error path", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("Forward failure: shows error banner, does not call onResolved", async () => {
    vi.mocked(api.releaseFlow).mockRejectedValueOnce(new Error("Network error"));
    const onResolved = vi.fn();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={onResolved} />);

    fireEvent.click(screen.getByRole("button", { name: "Forward" }));

    await waitFor(() => expect(screen.getByText("Network error")).toBeTruthy());
    expect(onResolved).not.toHaveBeenCalled();
  });

  it("Drop failure: shows error banner, does not call onResolved", async () => {
    vi.mocked(api.dropFlow).mockRejectedValueOnce(new Error("Drop failed"));
    const onResolved = vi.fn();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={onResolved} />);

    fireEvent.click(screen.getByRole("button", { name: "Drop" }));

    await waitFor(() => expect(screen.getByText("Drop failed")).toBeTruthy());
    expect(onResolved).not.toHaveBeenCalled();
  });

  it("Pass Through failure: shows error banner, does not call onResolved", async () => {
    vi.mocked(api.releaseFlowUnmodified).mockRejectedValueOnce(new Error("Timeout"));
    const onResolved = vi.fn();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={onResolved} />);

    fireEvent.click(screen.getByRole("button", { name: "Pass Through" }));

    await waitFor(() => expect(screen.getByText("Timeout")).toBeTruthy());
    expect(onResolved).not.toHaveBeenCalled();
  });

  it("error clears on subsequent attempt", async () => {
    vi.mocked(api.dropFlow)
      .mockRejectedValueOnce(new Error("first failure"))
      .mockResolvedValueOnce(undefined);
    const onResolved = vi.fn();
    render(<BreakpointEditor pausedFlow={mockPausedFlow} onResolved={onResolved} />);

    // First click — should fail
    fireEvent.click(screen.getByRole("button", { name: "Drop" }));
    await waitFor(() => expect(screen.getByText("first failure")).toBeTruthy());

    // Second click — should succeed and clear the error
    fireEvent.click(screen.getByRole("button", { name: "Drop" }));
    await waitFor(() => expect(onResolved).toHaveBeenCalledTimes(1));
    expect(screen.queryByText("first failure")).toBeNull();
  });
});
