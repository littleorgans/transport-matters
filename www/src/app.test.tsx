import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./app";

// Mock EventSource since jsdom does not provide it
beforeEach(() => {
  vi.stubGlobal(
    "EventSource",
    class MockEventSource {
      onopen: (() => void) | null = null;
      onerror: (() => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      close = vi.fn();
    },
  );
});

describe("App", () => {
  it("renders the app title", () => {
    render(<App />);
    expect(screen.getByText("Manicure")).toBeInTheDocument();
  });

  it("shows empty state prompt", () => {
    render(<App />);
    expect(screen.getByText("Select an exchange to inspect")).toBeInTheDocument();
  });
});
