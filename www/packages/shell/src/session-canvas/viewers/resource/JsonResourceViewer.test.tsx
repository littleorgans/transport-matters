import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { JsonContentResponse } from "../../api/resourceContent";
import { JsonResourceViewer } from "./JsonResourceViewer";

function makeContent(overrides: Partial<JsonContentResponse> = {}): JsonContentResponse {
  return {
    kind: "json",
    id: "res-1",
    title: "payload.json",
    mediaType: "application/json",
    contentLength: null,
    contentProvenance: "captured",
    provenance: {},
    value: { name: "x", nested: { n: 1 }, list: [1, 2] },
    text: null,
    truncated: false,
    ...overrides,
  };
}

describe("JsonResourceViewer", () => {
  it("renders the tree with object keys by default", () => {
    render(<JsonResourceViewer content={makeContent()} />);
    expect(screen.getByText("name")).toBeInTheDocument();
    expect(screen.getByText("nested")).toBeInTheDocument();
    expect(screen.getByText("list")).toBeInTheDocument();
  });

  it("renders the stringified JSON when the Raw toggle is pressed", () => {
    const { container } = render(<JsonResourceViewer content={makeContent()} />);
    fireEvent.click(screen.getByRole("button", { name: "Raw" }));
    expect(container.textContent).toContain('"name": "x"');
  });

  it("shows content.text verbatim in raw mode when present", () => {
    const { container } = render(
      <JsonResourceViewer content={makeContent({ value: { a: 1 }, text: '{"a":1}' })} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Raw" }));
    expect(container.textContent).toContain('{"a":1}');
  });

  it("renders a copy button", () => {
    render(<JsonResourceViewer content={makeContent()} />);
    expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument();
  });

  it("shows the truncation note only when truncated", () => {
    const { rerender } = render(<JsonResourceViewer content={makeContent()} />);
    expect(screen.queryByText(/truncated by the server/i)).not.toBeInTheDocument();
    rerender(<JsonResourceViewer content={makeContent({ truncated: true })} />);
    expect(screen.getByText(/truncated by the server/i)).toBeInTheDocument();
  });
});
