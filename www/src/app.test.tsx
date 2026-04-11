import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./app";
import { useUIStore } from "./stores/uiStore";

function renderWithProviders(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

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
  // Reset store between tests
  useUIStore.setState({ pausedFlow: null, selectedId: null, activeTab: "log" });
});

describe("App", () => {
  it("renders the app title", () => {
    renderWithProviders(<App />);
    expect(screen.getByText("Manicure")).toBeInTheDocument();
  });

  it("shows empty state prompt", () => {
    renderWithProviders(<App />);
    expect(screen.getByText("Select an exchange to inspect")).toBeInTheDocument();
  });
});
