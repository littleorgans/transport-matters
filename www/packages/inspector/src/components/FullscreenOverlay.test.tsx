import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { FullscreenOverlay } from "./FullscreenOverlay";

const classes = (el: Element) => el.className.split(/\s+/);

describe("FullscreenOverlay", () => {
  it("renders position:fixed (and NOT relative) with a scroll region when open", () => {
    const { container } = render(
      <FullscreenOverlay isOpen label="Close" onClose={() => {}}>
        <div data-testid="child">content</div>
      </FullscreenOverlay>,
    );
    const wrapper = container.firstElementChild as HTMLElement;
    // Regression guard: `relative` and `fixed` are both position utilities.
    // Tailwind emits `.relative` after `.fixed`, so if both are present the
    // overlay stays in-flow and never covers the chrome. Open state must be
    // fixed-only.
    expect(classes(wrapper)).toContain("fixed");
    expect(classes(wrapper)).toContain("inset-0");
    expect(classes(wrapper)).not.toContain("relative");
    // A scroll region must exist so tall payloads never clip.
    expect(container.querySelector(".overflow-y-auto")).not.toBeNull();
  });

  it("renders layout-neutral (display:contents, no box) when closed with inlineWhenClosed", () => {
    const { container, getByTestId } = render(
      <FullscreenOverlay isOpen={false} inlineWhenClosed label="Close" onClose={() => {}}>
        <div data-testid="child">content</div>
      </FullscreenOverlay>,
    );
    const wrapper = container.firstElementChild as HTMLElement;
    // Closed-inline must add no box of its own — `contents` keeps the child's
    // parent flex context so a `flex-1 overflow-y-auto` pane still scrolls.
    expect(classes(wrapper)).toContain("contents");
    expect(classes(wrapper)).not.toContain("fixed");
    expect(classes(wrapper)).not.toContain("relative");
    // single-instance: children stay mounted inline when closed
    expect(getByTestId("child")).toBeTruthy();
  });

  it("renders nothing when closed and not inline", () => {
    const { container } = render(
      <FullscreenOverlay isOpen={false} label="Close" onClose={() => {}}>
        <div>content</div>
      </FullscreenOverlay>,
    );
    expect(container.firstChild).toBeNull();
  });

  it("invokes onClose from the close button only when open", () => {
    const onClose = vi.fn();
    const { getByLabelText } = render(
      <FullscreenOverlay isOpen label="Close" onClose={onClose}>
        <div>content</div>
      </FullscreenOverlay>,
    );
    fireEvent.click(getByLabelText("Close"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
