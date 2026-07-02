import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TRUNCATION_NOTE, TruncationNote } from "./TruncationNote";

describe("TruncationNote", () => {
  it("renders the canonical wording with the caller's class", () => {
    render(<TruncationNote className="canvas-text__note" />);
    expect(screen.getByText(TRUNCATION_NOTE)).toHaveClass("canvas-text__note");
  });

  it("renders an overridden message verbatim", () => {
    const sourceVariant = "Partial content shown (source truncated by the server).";
    render(<TruncationNote className="canvas-md__truncated" message={sourceVariant} />);
    expect(screen.getByText(sourceVariant)).toBeInTheDocument();
  });
});
