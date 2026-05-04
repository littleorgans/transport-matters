import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RouteLayout, type RouteLayoutProps } from "./routeLayout";

const baseProps: RouteLayoutProps = {
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
};

function renderLayout(overrides: Partial<RouteLayoutProps> = {}) {
  return render(<RouteLayout {...baseProps} {...overrides} />);
}

describe("RouteLayout", () => {
  it("renders the waiting screen from prepared shell state", () => {
    renderLayout();

    expect(screen.getByRole("heading", { name: "Transport Matters" })).toBeInTheDocument();
    expect(screen.getAllByRole("img", { name: "Transport Matters" })).toHaveLength(2);
    expect(screen.getByText("Waiting for exchanges")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show history" })).toBeInTheDocument();
  });

  it("renders non-intercept routes without browser shell hooks", () => {
    renderLayout({ activeRoute: "trace", includeHistory: true });

    expect(screen.getByRole("heading", { name: "Trace" })).toBeInTheDocument();
    expect(screen.queryByText("Waiting for exchanges")).not.toBeInTheDocument();
  });
});
