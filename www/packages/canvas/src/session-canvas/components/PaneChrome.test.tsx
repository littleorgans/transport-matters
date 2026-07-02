import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PaneChrome } from "./PaneChrome";

function setup(props: Partial<Parameters<typeof PaneChrome>[0]> = {}) {
  return render(
    <PaneChrome
      badge="captured-run"
      compact
      focused={false}
      state="default"
      title="Claude"
      titleId="t"
      {...props}
    >
      <div>body</div>
    </PaneChrome>,
  );
}

describe("PaneChrome minimize affordance", () => {
  it("omits the minimize button when no onMinimize is provided (production chrome unchanged)", () => {
    setup({ onClose: vi.fn() });

    expect(screen.queryByRole("button", { name: "Minimize Claude" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close Claude" })).toBeInTheDocument();
  });

  it("renders Minimize before Close so Close stays the rightmost control", () => {
    const onMinimize = vi.fn();
    const onClose = vi.fn();
    setup({ onMinimize, onClose });

    const buttons = screen.getAllByRole("button");
    const labels = buttons.map((button) => button.getAttribute("aria-label"));
    expect(labels.indexOf("Minimize Claude")).toBeLessThan(labels.indexOf("Close Claude"));

    fireEvent.click(screen.getByRole("button", { name: "Minimize Claude" }));
    expect(onMinimize).toHaveBeenCalledTimes(1);
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("PaneChrome header frame gesture", () => {
  // The action controls sit inside the header, which carries the double-click-to-frame gesture. A
  // rapid close/minimize can land two clicks on the same button → a header dblclick → framePane,
  // which frames the pane right as it is being removed (the "frame zoom" flicker). Controls must NOT
  // bubble a double-click to the header.
  it("does not fire the header double-click when a control button is double-clicked", () => {
    const onHeaderDoubleClick = vi.fn();
    setup({
      onClose: vi.fn(),
      onMinimize: vi.fn(),
      onExpand: vi.fn(),
      onFrame: vi.fn(),
      onHeaderDoubleClick,
    });

    fireEvent.doubleClick(screen.getByRole("button", { name: "Close Claude" }));
    fireEvent.doubleClick(screen.getByRole("button", { name: "Minimize Claude" }));

    expect(onHeaderDoubleClick).not.toHaveBeenCalled();
  });

  it("still fires the header double-click (frame gesture) on the title region", () => {
    const onHeaderDoubleClick = vi.fn();
    setup({ onClose: vi.fn(), onHeaderDoubleClick });

    fireEvent.doubleClick(screen.getByText("Claude"));

    expect(onHeaderDoubleClick).toHaveBeenCalledTimes(1);
  });
});
