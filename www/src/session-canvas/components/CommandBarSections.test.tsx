import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CommandBarSections } from "./CommandBarSections";

function setup() {
  return render(
    <CommandBarSections
      primary={<button type="button">Add pane</button>}
      secondary={<button type="button">Min width</button>}
      secondaryLabel="Layout"
    />,
  );
}

describe("CommandBarSections", () => {
  it("shows the primary group and hides the secondary group by default", () => {
    setup();

    expect(screen.getByRole("button", { name: "Add pane" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Min width" })).not.toBeInTheDocument();
  });

  it("flips to the secondary group when the toggle is pressed, then back", () => {
    setup();
    const toggle = screen.getByRole("button", { name: "Layout" });

    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Min width" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Add pane" })).not.toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Add pane" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Min width" })).not.toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-pressed", "false");
  });
});
