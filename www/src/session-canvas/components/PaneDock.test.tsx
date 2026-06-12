import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { clearActiveDockDrag, PANE_REF_MIME, readActiveDockDrag } from "../dnd/dockDragSource";
import { clearDropTarget, setDropTarget, useDropTargetStore } from "../dnd/dropTargetStore";
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

  describe("drag source", () => {
    afterEach(() => {
      clearActiveDockDrag();
      clearDropTarget();
    });

    function openMenuAndGetRow(name: string): HTMLElement {
      fireEvent.click(screen.getByRole("button", { name: "Minimized panes, 3" }));
      const row = screen.getByRole("menuitem", { name }).closest(".canvas-dock__row");
      if (!(row instanceof HTMLElement)) throw new Error(`no dock row for ${name}`);
      return row;
    }

    it("lifts a row with the pane-ref mime and publishes the holder", () => {
      render(<PaneDock docked={DOCKED} onClose={vi.fn()} onRestore={vi.fn()} />);
      // the null-ref demo row: its title deterministically falls back to the paneId
      const row = openMenuAndGetRow("lab-2");
      const setData = vi.fn();

      fireEvent.dragStart(row, { dataTransfer: { setData, effectAllowed: "none" } });

      expect(setData).toHaveBeenCalledWith(
        PANE_REF_MIME,
        JSON.stringify({ paneId: "lab-2", ref: null }),
      );
      expect(readActiveDockDrag()).toEqual({ paneId: "lab-2", ref: null });
    });

    it("clears the holder and the overlay on dragend, drop or not", () => {
      render(<PaneDock docked={DOCKED} onClose={vi.fn()} onRestore={vi.fn()} />);
      const row = openMenuAndGetRow("lab-2");
      fireEvent.dragStart(row, { dataTransfer: { setData: vi.fn(), effectAllowed: "none" } });
      setDropTarget({ kind: "surface" });

      fireEvent.dragEnd(row);

      expect(readActiveDockDrag()).toBeNull();
      expect(useDropTargetStore.getState().target).toBeNull();
    });

    it("never initiates a drag from the kill button", () => {
      render(<PaneDock docked={DOCKED} onClose={vi.fn()} onRestore={vi.fn()} />);
      fireEvent.click(screen.getByRole("button", { name: "Minimized panes, 3" }));
      const kill = screen.getByRole("menuitem", { name: "Close lab-2" });
      const setData = vi.fn();

      fireEvent.dragStart(kill, { dataTransfer: { setData, effectAllowed: "none" } });

      expect(setData).not.toHaveBeenCalled();
      expect(readActiveDockDrag()).toBeNull();
    });
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
