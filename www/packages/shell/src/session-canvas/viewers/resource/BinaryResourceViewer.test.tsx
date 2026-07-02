import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { BinaryContentResponse } from "../../api/resourceContent";
import { BinaryResourceViewer } from "./BinaryResourceViewer";

function makeContent(overrides: Partial<BinaryContentResponse> = {}): BinaryContentResponse {
  return {
    kind: "binary",
    id: "res-1",
    title: "payload.bin",
    mediaType: "application/octet-stream",
    contentLength: 2048,
    contentProvenance: "captured",
    provenance: {},
    downloadUrl: "https://example.com/d/res-1",
    sha256: "abc123def456",
    tooLarge: false,
    ...overrides,
  };
}

describe("BinaryResourceViewer", () => {
  it("renders the metadata rows", () => {
    render(<BinaryResourceViewer content={makeContent()} />);
    expect(screen.getByText("payload.bin")).toBeInTheDocument();
    expect(screen.getByText("application/octet-stream")).toBeInTheDocument();
    expect(screen.getByText("abc123def456")).toBeInTheDocument();
  });

  it("formats a 2048-byte length as 2.0 KB", () => {
    render(<BinaryResourceViewer content={makeContent()} />);
    expect(screen.getByText("2.0 KB")).toBeInTheDocument();
  });

  it("falls back to placeholder text for missing media type and sha256", () => {
    render(<BinaryResourceViewer content={makeContent({ mediaType: null, sha256: null })} />);
    expect(screen.getByText("unknown")).toBeInTheDocument();
    expect(screen.getByText("unavailable")).toBeInTheDocument();
  });

  it("renders an open-externally link pointing at the download url", () => {
    const downloadUrl = "https://example.com/d/res-1";
    render(<BinaryResourceViewer content={makeContent({ downloadUrl: downloadUrl })} />);
    const link = screen.getByRole("link", { name: /open externally/i });
    expect(link).toHaveAttribute("href", downloadUrl);
    expect(link.getAttribute("href")).toBe(downloadUrl);
  });

  it("degrades to a disabled button when there is no download url", () => {
    render(<BinaryResourceViewer content={makeContent({ downloadUrl: null })} />);
    const button = screen.getByRole("button", { name: /open externally/i });
    expect(button).toBeDisabled();
    expect(screen.queryByRole("link", { name: /open externally/i })).toBeNull();
  });

  it("degrades to a disabled button when the download url has an unsafe scheme", () => {
    // A javascript: (or other non-http) downloadUrl must never reach the DOM as
    // a navigable href. The same scheme allowlist used for markdown links guards
    // the binary action (defense-in-depth), so an unsafe value degrades exactly
    // like a missing url.
    render(<BinaryResourceViewer content={makeContent({ downloadUrl: "javascript:alert(1)" })} />);
    expect(screen.queryByRole("link", { name: /open externally/i })).toBeNull();
    expect(screen.getByRole("button", { name: /open externally/i })).toBeDisabled();
  });
});
