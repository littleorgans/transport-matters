import { fireEvent, render, renderHook, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { useRouteHotkeys } from "../hooks/useRouteHotkeys";
import { useUIStore } from "../stores/uiStore";
import { RouteRail } from "./RouteRail";

beforeEach(() => {
  useUIStore.setState({ activeRoute: "intercept" });
});

describe("RouteRail", () => {
  it("renders all four routes", () => {
    render(<RouteRail />);
    expect(screen.getByRole("button", { name: /Intercept/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Overlays/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Trace/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Recall/ })).toBeInTheDocument();
  });

  it("marks the active route with aria-current='page'", () => {
    render(<RouteRail />);
    const intercept = screen.getByRole("button", { name: /Intercept/ });
    expect(intercept).toHaveAttribute("aria-current", "page");
    const trace = screen.getByRole("button", { name: /Trace/ });
    expect(trace).not.toHaveAttribute("aria-current");
  });

  it("clicking a route updates the store", () => {
    render(<RouteRail />);
    fireEvent.click(screen.getByRole("button", { name: /Overlays/ }));
    expect(useUIStore.getState().activeRoute).toBe("overlays");
  });

  it("shows SOON marker on unavailable routes only", () => {
    render(<RouteRail />);
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
