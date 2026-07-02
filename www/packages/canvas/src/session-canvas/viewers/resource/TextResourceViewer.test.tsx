import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TextContentResponse, TextRange } from "../../api/resourceContent";
import { TextResourceViewer } from "./TextResourceViewer";

function makeContent(overrides: Partial<TextContentResponse> = {}): TextContentResponse {
  return {
    kind: "text",
    id: "res-1",
    title: "notes.txt",
    mediaType: "text/plain",
    contentLength: 100,
    contentProvenance: "captured",
    provenance: {},
    text: "line one\nline two",
    encoding: "utf-8",
    range: null,
    truncated: false,
    ...overrides,
  };
}

describe("TextResourceViewer", () => {
  it("renders each line with a line-number gutter", () => {
    render(<TextResourceViewer content={makeContent()} />);
    expect(screen.getByText("line one")).toBeInTheDocument();
    expect(screen.getByText("line two")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("renders a Copy button", () => {
    render(<TextResourceViewer content={makeContent()} />);
    expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument();
  });

  it("shows a byte-range note when a range is present", () => {
    const range: TextRange = { start: 0, end: 10, total: 100 };
    render(<TextResourceViewer content={makeContent({ range, truncated: true })} />);
    expect(screen.getByText(/Showing bytes 0–10 of 100/)).toBeInTheDocument();
  });

  it("shows a truncated note when truncated without a range", () => {
    render(<TextResourceViewer content={makeContent({ truncated: true })} />);
    expect(
      screen.getByText(/Partial content shown \(truncated by the server\)\./),
    ).toBeInTheDocument();
  });

  it("shows no note when not truncated and range is null", () => {
    const { container } = render(<TextResourceViewer content={makeContent()} />);
    expect(container.querySelector(".canvas-text__note")).toBeNull();
  });
});
