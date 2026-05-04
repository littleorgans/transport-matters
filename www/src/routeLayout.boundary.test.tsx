import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RouteLayoutProps } from "./routeLayout";

function props(overrides: Partial<RouteLayoutProps> = {}): RouteLayoutProps {
  return {
    connected: true,
    mode: "off",
    onToggleArm: vi.fn(),
    breakpointError: false,
    exchanges: [],
    trackTree: [],
    metaRunId: "run-current",
    includeHistory: false,
    onIncludeHistoryChange: vi.fn(),
    selectedId: null,
    onSelectExchange: vi.fn(),
    pausedFlow: null,
    onPausedFlowResolved: vi.fn(),
    activeRoute: "intercept",
    onActiveRouteChange: vi.fn(),
    collapsedTrackIds: [],
    onToggleCollapsedTrack: vi.fn(),
    ...overrides,
  };
}

async function renderSharedLayout(overrides: Partial<RouteLayoutProps> = {}) {
  cleanup();
  vi.resetModules();
  vi.stubGlobal(
    "EventSource",
    vi.fn(() => {
      throw new Error("RouteLayout must not construct browser transport");
    }),
  );
  vi.stubGlobal(
    "fetch",
    vi.fn(() => {
      throw new Error("RouteLayout must not fetch API data");
    }),
  );
  vi.doMock("./stores/uiStore", () => ({
    useUIStore: () => {
      throw new Error("RouteLayout must render from props, not persisted browser UI state");
    },
  }));
  const { RouteLayout } = await import("./routeLayout");
  return render(<RouteLayout {...props(overrides)} />);
}

afterEach(() => {
  vi.doUnmock("./stores/uiStore");
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("RouteLayout shared boundary", () => {
  it("renders waiting, intercept, and non-intercept routes from props only", async () => {
    const addEventListener = vi.spyOn(window, "addEventListener");

    await renderSharedLayout();
    expect(screen.getByText("Waiting for exchanges")).toBeInTheDocument();

    await renderSharedLayout({ includeHistory: true });
    expect(screen.getByText("No captured history in this workspace")).toBeInTheDocument();
    expect(screen.getByText("Select an exchange to inspect")).toBeInTheDocument();

    await renderSharedLayout({ activeRoute: "trace", includeHistory: true });
    expect(screen.getByRole("heading", { name: "Trace" })).toBeInTheDocument();
    expect(addEventListener).not.toHaveBeenCalledWith("keydown", expect.any(Function));
  });
});
