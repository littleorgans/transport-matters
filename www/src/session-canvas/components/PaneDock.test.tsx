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
  { paneId: "lab-2", ref: null }, // demo card/ruler stub: no viewer ref
];

describe("PaneDock", () => {
  it("renders nothing when the dock is empty", () => {
    const { container } = render(<PaneDock docked={[]} onRestore={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a count-badged chip and keeps the menu closed until clicked", () => {
    render(<PaneDock docked={DOCKED} onRestore={vi.fn()} />);
    const chip = screen.getByRole("button", { name: "Minimized panes, 3" });
    expect(chip).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("lists the minimized panes (most-recent first) and restores the one selected", () => {
    const onRestore = vi.fn();
    render(<PaneDock docked={DOCKED} onRestore={onRestore} />);

    fireEvent.click(screen.getByRole("button", { name: "Minimized panes, 3" }));
    const items = screen.getAllByRole("menuitem");
    expect(items).toHaveLength(3);

    const terminalRow = items[1];
    if (!terminalRow) throw new Error("expected a second dock row");
    fireEvent.click(terminalRow); // lab-1 (terminal), order preserved from the docked array
    expect(onRestore).toHaveBeenCalledWith("lab-1");
    // Selecting closes the menu.
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});
