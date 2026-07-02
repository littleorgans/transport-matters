import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { WindowDragRegion } from "./WindowDragRegion";

describe("WindowDragRegion", () => {
  it("renders nothing in a plain browser", () => {
    const { container } = render(<WindowDragRegion desktop={false} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders an inert top drag strip inside the desktop shell", () => {
    const { container } = render(<WindowDragRegion desktop />);
    const strip = container.querySelector(".window-drag-region");
    expect(strip).not.toBeNull();
    expect(strip).toHaveAttribute("aria-hidden", "true");
  });
});
