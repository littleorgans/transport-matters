import { fireEvent, render, renderHook, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useRouteHotkeys } from "../hooks/useRouteHotkeys";
import type { Route } from "../stores/uiStore";
import { useUIStore } from "../stores/uiStore";
import { RouteRail } from "./RouteRail";

beforeEach(() => {
  useUIStore.setState({ activeRoute: "intercept" });
});

function renderRouteRail(activeRoute: Route = "intercept", onActiveRouteChange = () => {}) {
  return render(<RouteRail activeRoute={activeRoute} onActiveRouteChange={onActiveRouteChange} />);
}

describe("RouteRail", () => {
  it("renders all four routes", () => {
    renderRouteRail();
    expect(screen.getByRole("button", { name: /Intercept/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Overlays/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Trace/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Recall/ })).toBeInTheDocument();
  });

  it("marks the active route with aria-current='page'", () => {
    renderRouteRail();
    const intercept = screen.getByRole("button", { name: /Intercept/ });
    expect(intercept).toHaveAttribute("aria-current", "page");
    const trace = screen.getByRole("button", { name: /Trace/ });
    expect(trace).not.toHaveAttribute("aria-current");
  });

  it("clicking a route reports the next route", () => {
    const onActiveRouteChange = vi.fn();
    renderRouteRail("intercept", onActiveRouteChange);
    fireEvent.click(screen.getByRole("button", { name: /Overlays/ }));
    expect(onActiveRouteChange).toHaveBeenCalledWith("overlays");
  });

  it("shows SOON marker on unavailable routes only", () => {
    renderRouteRail();
    // Intercept and Overlays are functional; Trace and Recall still wear SOON.
    const soonMarkers = screen.getAllByText("SOON");
    expect(soonMarkers).toHaveLength(2);
  });
});

describe("useRouteHotkeys", () => {
  it("digit keys switch routes", () => {
    renderHook(() => useRouteHotkeys());
    fireEvent.keyDown(window, { key: "2" });
    expect(useUIStore.getState().activeRoute).toBe("overlays");
    fireEvent.keyDown(window, { key: "3" });
    expect(useUIStore.getState().activeRoute).toBe("trace");
    fireEvent.keyDown(window, { key: "4" });
    expect(useUIStore.getState().activeRoute).toBe("recall");
    fireEvent.keyDown(window, { key: "1" });
    expect(useUIStore.getState().activeRoute).toBe("intercept");
  });

  it("leader 'g' then letter switches routes", () => {
    renderHook(() => useRouteHotkeys());
    fireEvent.keyDown(window, { key: "g" });
    fireEvent.keyDown(window, { key: "o" });
    expect(useUIStore.getState().activeRoute).toBe("overlays");
    fireEvent.keyDown(window, { key: "g" });
    fireEvent.keyDown(window, { key: "t" });
    expect(useUIStore.getState().activeRoute).toBe("trace");
    fireEvent.keyDown(window, { key: "g" });
    fireEvent.keyDown(window, { key: "r" });
    expect(useUIStore.getState().activeRoute).toBe("recall");
  });

  it("ignores keypresses while typing in inputs", () => {
    renderHook(() => useRouteHotkeys());
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();
    fireEvent.keyDown(input, { key: "2" });
    expect(useUIStore.getState().activeRoute).toBe("intercept");
    document.body.removeChild(input);
  });

  it("ignores digit keys with modifier held", () => {
    renderHook(() => useRouteHotkeys());
    fireEvent.keyDown(window, { key: "2", metaKey: true });
    expect(useUIStore.getState().activeRoute).toBe("intercept");
  });
});
