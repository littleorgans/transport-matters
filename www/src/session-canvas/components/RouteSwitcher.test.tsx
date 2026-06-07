import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RouteSwitcher } from "./RouteSwitcher";

const realLocation = window.location;

// jsdom's location.assign is non-configurable (spyOn fails), but the location property on window
// is configurable — so replace the whole object with a stub for the duration of a test.
function stubLocation(pathname: string, search = ""): ReturnType<typeof vi.fn> {
  const assign = vi.fn();
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { pathname, search, assign },
  });
  return assign;
}

describe("RouteSwitcher", () => {
  afterEach(() => {
    Object.defineProperty(window, "location", { configurable: true, value: realLocation });
    vi.restoreAllMocks();
  });

  it("renders the canvas surfaces in a nav landmark and marks the active one", () => {
    stubLocation("/canvas");
    render(<RouteSwitcher />);

    expect(screen.getByRole("navigation", { name: "Canvas surfaces" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Canvas" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "Lab" })).not.toHaveAttribute("aria-current");
  });

  it("navigates to the target route, preserving the query string", () => {
    const assign = stubLocation("/canvas", "?workspace_hash=abc&cli=claude");
    render(<RouteSwitcher />);
    fireEvent.click(screen.getByRole("button", { name: "Lab" }));

    expect(assign).toHaveBeenCalledWith("/canvas-lab?workspace_hash=abc&cli=claude");
  });

  it("does not navigate when the already-active route is clicked", () => {
    const assign = stubLocation("/canvas");
    render(<RouteSwitcher />);
    fireEvent.click(screen.getByRole("button", { name: "Canvas" }));

    expect(assign).not.toHaveBeenCalled();
  });
});
