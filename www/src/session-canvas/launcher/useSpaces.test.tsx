import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resetApiTransport, setApiTransport } from "../../api";
import { useSpaces } from "./useSpaces";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

afterEach(() => resetApiTransport());

describe("useSpaces", () => {
  it("returns the fetched spaces once loaded, [] before", async () => {
    const items = [{ spaceId: "s1", label: "tm", kind: "repo", worktrees: [] }];
    setApiTransport({
      request: vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ items }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    });

    const { result } = renderHook(() => useSpaces(true), { wrapper });
    expect(result.current).toEqual([]);
    await waitFor(() => expect(result.current).toEqual(items));
  });
});
