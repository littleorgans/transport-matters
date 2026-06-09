import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { DockedPane } from "../model/paneRecords";
import { PaneDock } from "./PaneDock";

const DOCKED: DockedPane[] = [
  {
    paneId: "claude:k1",
    ref: { kind: "captured-run", owner: "local", provider: "claude", runKey: "claude:k1" },
  },
  { paneId: "lab-1", ref: { kind: "terminal", owner: "local" } },
  { paneId: "lab-2", ref: null }, // demo card/ruler stub: no viewer ref, title falls back to paneId
];

describe("PaneDock", () => {
  it("renders nothing when the dock is empty", () => {
    const { container } = render(<PaneDock docked={[]} onClose={vi.fn()} onRestore={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a count-badged chip and keeps the menu closed until clicked", () => {
    render(<PaneDock docked={DOCKED} onClose={vi.fn()} onRestore={vi.fn()} />);
    const chip = screen.getByRole("button", { name: "Minimized panes, 3" });
    expect(chip).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("lists each pane with a restore + a kill action and restores the one selected", () => {
    const onRestore = vi.fn();
    render(<PaneDock docked={DOCKED} onClose={vi.fn()} onRestore={onRestore} />);

    fireEvent.click(screen.getByRole("button", { name: "Minimized panes, 3" }));
    // Three rows, two menuitems each (restore title + [×] kill).
    expect(screen.getAllByRole("menuitem")).toHaveLength(6);

    // The null-ref demo pane's title falls back to its paneId, so it is a deterministic target.
    // RTL matches a string `name` against the FULL accessible name, so "lab-2" hits the restore
    // menuitem and not the kill button's "Close lab-2".
    fireEvent.click(screen.getByRole("menuitem", { name: "lab-2" }));
    expect(onRestore).toHaveBeenCalledWith("lab-2");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("closes/kills a docked pane via its [×] without restoring it", () => {
    const onRestore = vi.fn();
    const onClose = vi.fn();
    render(<PaneDock docked={DOCKED} onClose={onClose} onRestore={onRestore} />);

    fireEvent.click(screen.getByRole("button", { name: "Minimized panes, 3" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Close lab-2" }));

    expect(onClose).toHaveBeenCalledWith("lab-2");
    expect(onRestore).not.toHaveBeenCalled();
    // Closing keeps the menu open so several entries can be cleared in one pass.
    expect(screen.getByRole("menu")).toBeInTheDocument();
  });
});
