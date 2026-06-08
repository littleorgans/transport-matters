import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ImageContentResponse } from "../../api/resourceContent";
import { ImageResourceViewer } from "./ImageResourceViewer";

function makeContent(overrides: Partial<ImageContentResponse> = {}): ImageContentResponse {
  return {
    kind: "image",
    id: "img-1",
    title: "Diagram",
    mediaType: "image/png",
    contentLength: null,
    contentProvenance: "captured",
    provenance: {},
    url: "https://example.com/pic.png",
    bytesBase64: null,
    width: null,
    height: null,
    alt: "An architecture diagram",
    ...overrides,
  };
}

describe("ImageResourceViewer", () => {
  it("renders an <img> with the url src and alt from content.alt", () => {
    render(<ImageResourceViewer content={makeContent()} />);
    const img = screen.getByRole("img");
    expect(img).toHaveAttribute("src", "https://example.com/pic.png");
    expect(img).toHaveAttribute("alt", "An architecture diagram");
  });

  it("zoom in raises the percentage label and reset returns it to 100%", () => {
    render(<ImageResourceViewer content={makeContent()} />);
    expect(screen.getByText("100%")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByText("125%")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Reset zoom" }));
    expect(screen.getByText("100%")).toBeInTheDocument();
  });

  it("builds a data: URL from bytesBase64 when url is null", () => {
    render(<ImageResourceViewer content={makeContent({ url: null, bytesBase64: "QUJD" })} />);
    const img = screen.getByRole("img");
    const src = img.getAttribute("src") ?? "";
    expect(src.startsWith("data:image/")).toBe(true);
    expect(src).toContain("QUJD");
  });

  it("shows the no-preview note and no img when url and bytes are null", () => {
    render(<ImageResourceViewer content={makeContent({ url: null, bytesBase64: null })} />);
    expect(screen.getByText("No image preview available.")).toBeInTheDocument();
    expect(screen.queryByRole("img")).toBeNull();
  });
});
