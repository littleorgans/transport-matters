import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { makeWrapper } from "./useExchangeStream.testSupport";
import { useTurnContent } from "./useTurnContent";

describe("useTurnContent", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetches turn content for a given id", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            user_text: "hi",
            response_text: "hello",
            stop_reason: "end_turn",
          }),
          { status: 200 },
        ),
      ),
    );

    const { qc, wrapper } = makeWrapper();
    const { result } = renderHook(() => useTurnContent("ex-001"), { wrapper });

    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data).toEqual({
      user_text: "hi",
      response_text: "hello",
      stop_reason: "end_turn",
    });
    expect(fetch).toHaveBeenCalledWith("/api/exchanges/ex-001/turn-content");

    const query = qc.getQueryCache().find({ queryKey: ["turn-content", "ex-001"] });
    const queryOptions = query?.options as { staleTime?: unknown } | undefined;
    expect(query?.queryKey).toEqual(["turn-content", "ex-001"]);
    expect(queryOptions?.staleTime).toBe(Number.POSITIVE_INFINITY);
  });

  it("does not fetch when id is empty", () => {
    vi.stubGlobal("fetch", vi.fn());

    const { wrapper } = makeWrapper();
    renderHook(() => useTurnContent(""), { wrapper });

    expect(fetch).not.toHaveBeenCalled();
  });
});
