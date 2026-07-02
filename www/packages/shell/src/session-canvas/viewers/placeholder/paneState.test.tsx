import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { type ResourcePaneState, ResourcePaneStateView } from "./paneState";
import { PROVENANCE_LABEL } from "./provenance";

const ALL_STATES: ResourcePaneState[] = [
  { status: "loading" },
  { status: "ready" },
  { status: "missing" },
  { status: "too-large" },
  { status: "binary-unsupported" },
  { status: "outside-workspace" },
  { status: "permission-denied" },
  { status: "debug-unavailable" },
];

describe("ResourcePaneStateView", () => {
  it("renders every one of the eight states without crashing", () => {
    for (const state of ALL_STATES) {
      const { unmount } = render(
        <ResourcePaneStateView provenance="captured" state={state}>
          <p>content</p>
        </ResourcePaneStateView>,
      );
      expect(document.querySelector(".canvas-resource-pane")).toBeInTheDocument();
      expect(document.querySelector(`[data-status="${state.status}"]`)).toBeInTheDocument();
      unmount();
    }
  });

  it("renders the ready content slot", () => {
    render(
      <ResourcePaneStateView provenance="captured" state={{ status: "ready" }}>
        <p>real content</p>
      </ResourcePaneStateView>,
    );
    expect(screen.getByText("real content")).toBeInTheDocument();
  });

  it("marks the loading state as busy", () => {
    render(<ResourcePaneStateView provenance="captured" state={{ status: "loading" }} />);
    expect(document.querySelector('[aria-busy="true"]')).toBeInTheDocument();
  });

  it("renders a stable missing pane that preserves provenance and an action, not a toast", () => {
    render(<ResourcePaneStateView provenance="captured" state={{ status: "missing" }} />);
    expect(screen.getByText(PROVENANCE_LABEL.captured)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("shows the preview byte range on a too-large pane when present", () => {
    render(
      <ResourcePaneStateView
        provenance="captured"
        state={{
          status: "too-large",
          byteSize: 4096,
          previewRange: { startByte: 0, endByte: 1024 },
        }}
      />,
    );
    expect(screen.getByText(/0 to 1024/)).toBeInTheDocument();
  });

  it("renders a stable too-large pane without a preview range", () => {
    expect(() =>
      render(<ResourcePaneStateView provenance="captured" state={{ status: "too-large" }} />),
    ).not.toThrow();
    expect(document.querySelector('[data-status="too-large"]')).toBeInTheDocument();
  });

  it("lets callers override the default actions", () => {
    render(
      <ResourcePaneStateView
        actions={[{ label: "Open externally" }]}
        provenance="raw-provider-debug"
        state={{ status: "binary-unsupported", mediaType: "application/pdf" }}
      />,
    );
    expect(screen.getByRole("button", { name: "Open externally" })).toBeInTheDocument();
    expect(screen.getByText(PROVENANCE_LABEL["raw-provider-debug"])).toBeInTheDocument();
  });

  it("renders a backend message override in place of the canned error detail", () => {
    render(
      <ResourcePaneStateView
        messageOverride="This resource was never correlated to a turn."
        provenance="captured"
        state={{ status: "missing" }}
      />,
    );
    expect(screen.getByText("This resource was never correlated to a turn.")).toBeInTheDocument();
    // The canned default detail is replaced, not appended.
    expect(
      screen.queryByText("This resource is no longer available in the run store."),
    ).not.toBeInTheDocument();
  });
});
