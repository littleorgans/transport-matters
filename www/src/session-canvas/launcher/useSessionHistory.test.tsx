import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";
import {
  installMockTransport,
  jsonResponse,
  makeSessionSummary,
  restoreTransport,
} from "../testUtils";
import { useSessionHistory } from "./useSessionHistory";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

afterEach(() => restoreTransport());

describe("useSessionHistory", () => {
  it("maps the four-state contract: [] + loading before, populated after", async () => {
    const items = [makeSessionSummary({ sessionId: "s1" })];
    installMockTransport(() => jsonResponse({ items, nextCursor: null }));

    const { result } = renderHook(() => useSessionHistory(null, true), { wrapper });

    expect(result.current.sessions).toEqual([]);
    expect(result.current.status).toBe("loading");
    await waitFor(() => expect(result.current.status).toBe("populated"));
    expect(result.current.sessions).toEqual(items);
  });

  it("reports empty when the store returns no sessions", async () => {
    installMockTransport(() => jsonResponse({ items: [], nextCursor: null }));

    const { result } = renderHook(() => useSessionHistory("hash-1", true), { wrapper });

    await waitFor(() => expect(result.current.status).toBe("empty"));
    expect(result.current.sessions).toEqual([]);
  });

  it("stays idle (loading, no fetch) until enabled", () => {
    let calls = 0;
    installMockTransport(() => {
      calls += 1;
      return jsonResponse({ items: [], nextCursor: null });
    });

    const { result } = renderHook(() => useSessionHistory(null, false), { wrapper });

    expect(result.current.status).toBe("loading");
    expect(calls).toBe(0);
  });
});
