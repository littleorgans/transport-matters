import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { dismissedPanelKey } from "../../stores/persistence";
import { DismissablePanel } from "./DismissablePanel";

beforeEach(() => {
  localStorage.clear();
});

describe("DismissablePanel", () => {
  it("renders title and body when not previously dismissed", () => {
    render(
      <DismissablePanel id="t-1" tone="info" title="Hello">
        <p>body copy</p>
      </DismissablePanel>,
    );

    expect(screen.getByText("Hello")).toBeInTheDocument();
    expect(screen.getByText("body copy")).toBeInTheDocument();
  });

  it("renders nothing when localStorage already marks the id dismissed", () => {
    localStorage.setItem(dismissedPanelKey("t-2"), "1");

    const { container } = render(
      <DismissablePanel id="t-2" tone="info" title="Hello">
        <p>body</p>
      </DismissablePanel>,
    );

    expect(container.firstChild).toBeNull();
  });

  it("hides the panel and persists the dismissal when × is clicked", () => {
    render(
      <DismissablePanel id="t-3" tone="warn" title="Heads up">
        <p>be careful</p>
      </DismissablePanel>,
    );

    const btn = screen.getByRole("button", { name: /Dismiss Heads up/i });
    fireEvent.click(btn);

    expect(screen.queryByText("Heads up")).toBeNull();
    expect(localStorage.getItem(dismissedPanelKey("t-3"))).toBe("1");
  });

  it("dismissals are scoped per id — dismissing A leaves B visible", () => {
    const { unmount } = render(
      <DismissablePanel id="id-A" tone="info" title="A title">
        <p>A</p>
      </DismissablePanel>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Dismiss A title/i }));
    // Unmount + fresh mount models the real "different panel in a later
    // render pass" scenario; rerender would keep the same useState
    // closure and mask per-id scoping.
    unmount();

    render(
      <DismissablePanel id="id-B" tone="info" title="B title">
        <p>B</p>
      </DismissablePanel>,
    );

    expect(screen.getByText("B title")).toBeInTheDocument();
    expect(localStorage.getItem(dismissedPanelKey("id-A"))).toBe("1");
    expect(localStorage.getItem(dismissedPanelKey("id-B"))).toBeNull();
  });

  it("survives localStorage being unavailable at read time", () => {
    const original = globalThis.localStorage;
    // Stub a localStorage that throws on every access — mimics private
    // mode / storage-disabled browsers. The panel should still render.
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      value: {
        getItem: () => {
          throw new Error("blocked");
        },
        setItem: () => {
          throw new Error("blocked");
        },
        removeItem: () => {},
        clear: () => {},
        length: 0,
        key: () => null,
      },
    });

    try {
      render(
        <DismissablePanel id="t-blocked" tone="info" title="Still here">
          <p>body</p>
        </DismissablePanel>,
      );
      expect(screen.getByText("Still here")).toBeInTheDocument();

      // And the dismiss click should not throw either.
      fireEvent.click(screen.getByRole("button", { name: /Dismiss Still here/i }));
      expect(screen.queryByText("Still here")).toBeNull();
    } finally {
      Object.defineProperty(globalThis, "localStorage", {
        configurable: true,
        value: original,
      });
    }
  });
});
