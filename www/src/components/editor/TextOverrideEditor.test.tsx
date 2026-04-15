import { fireEvent, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { describe, expect, it, vi } from "vitest";
import { TextOverrideEditor } from "./TextOverrideEditor";

// Shared no-op handlers so individual tests can override only what they
// exercise. ``ref`` is threaded through for parity with real use — the
// auto-sizing effect in ``useEditableOverride`` reads it.
function renderEditor(overrides: Partial<React.ComponentProps<typeof TextOverrideEditor>> = {}) {
  const props: React.ComponentProps<typeof TextOverrideEditor> = {
    original: "hello world",
    value: "hello world",
    onChange: vi.fn(),
    onBlur: vi.fn(),
    textareaRef: createRef<HTMLTextAreaElement>(),
    isModified: false,
    onReset: vi.fn(),
    ...overrides,
  };
  const result = render(<TextOverrideEditor {...props} />);
  return { ...result, props };
}

describe("TextOverrideEditor", () => {
  // When the draft matches the pristine value the editor is chromeless:
  // no tablist, no RESET — just the textarea. This mirrors the cold-start
  // case where typing hasn't produced an override yet.
  it("renders just the textarea when not modified", () => {
    renderEditor({ isModified: false });
    expect(screen.getByRole("textbox")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /reset/i })).not.toBeInTheDocument();
  });

  // First keystroke that actually diverges from original flips the
  // chrome on: the EDIT | DIFF tabs and the reset button appear.
  it("shows tab bar with RESET when modified", () => {
    renderEditor({ isModified: true, value: "hello there" });
    expect(screen.getByRole("tablist")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /edit/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /diff/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reset text override/i })).toBeInTheDocument();
  });

  // EDIT tab is selected on initial modified render so the first click
  // lands in a writable surface — not in a read-only diff pane.
  it("starts on the EDIT tab and shows the textarea", () => {
    renderEditor({ isModified: true, value: "hello there" });
    const editTab = screen.getByRole("tab", { name: /edit/i });
    expect(editTab).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });

  // Clicking DIFF runs the word-level diff and renders sage <ins> for
  // additions, rose <del> for removals, and dimmed spans for unchanged
  // runs. Assert on the semantic tags so brittle class-name changes
  // don't tank the test.
  it("renders added and removed runs when switching to DIFF", () => {
    const { container } = renderEditor({
      isModified: true,
      original: "alpha beta gamma",
      value: "alpha delta gamma",
    });
    fireEvent.click(screen.getByRole("tab", { name: /diff/i }));
    expect(screen.getByRole("tab", { name: /diff/i })).toHaveAttribute("aria-selected", "true");
    // Added word present in <ins>, removed word present in <del>.
    expect(container.querySelector("ins")?.textContent).toContain("delta");
    expect(container.querySelector("del")?.textContent).toContain("beta");
    // Textarea is replaced by the diff pane while DIFF is active.
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  // RESET is the only externally visible affordance the editor owns —
  // the parent hook handles the actual override removal, so the test
  // asserts the call-through contract.
  it("fires onReset when the reset button is clicked", () => {
    const onReset = vi.fn();
    renderEditor({ isModified: true, value: "hello there", onReset });
    fireEvent.click(screen.getByRole("button", { name: /reset text override/i }));
    expect(onReset).toHaveBeenCalledTimes(1);
  });

  // Post-reset flow: user sits on DIFF, clicks RESET, ``isModified``
  // flips back to false, then on the next edit ``isModified`` flips
  // true again. Tab state must snap back to EDIT on the modified→clean
  // transition so the re-entry into modification lands in a writable
  // pane, not the now-empty DIFF.
  it("snaps back to EDIT when modified flips off and on again", () => {
    const { rerender, props } = renderEditor({
      isModified: true,
      original: "alpha beta",
      value: "alpha gamma",
    });
    fireEvent.click(screen.getByRole("tab", { name: /diff/i }));
    expect(screen.getByRole("tab", { name: /diff/i })).toHaveAttribute("aria-selected", "true");

    // Simulate parent dropping the override after a reset.
    rerender(
      <TextOverrideEditor {...props} isModified={false} value="alpha beta" original="alpha beta" />,
    );
    // Chromeless again — no tabs to assert against.
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();

    // Re-enter the modified state with a fresh edit. Tab state should
    // be EDIT, not the stale DIFF selection from before reset.
    rerender(
      <TextOverrideEditor {...props} isModified={true} original="alpha beta" value="alpha zeta" />,
    );
    expect(screen.getByRole("tab", { name: /edit/i })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });
});
