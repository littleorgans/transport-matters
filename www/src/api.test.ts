import { afterEach, describe, expect, it, vi } from "vitest";
import { createApiTransport, fetchTurnContent, resetApiTransport, setApiTransport } from "./api";

function stubFetch(body: unknown, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("fetchTurnContent", () => {
  afterEach(() => {
    resetApiTransport();
    vi.unstubAllGlobals();
  });

  it("fetches lazy turn content for an encoded exchange id", async () => {
    const body = {
      user_text: "show me the thing",
      response_text: "here it is",
      stop_reason: "end_turn",
    };
    const fetchMock = stubFetch(body);

    await expect(fetchTurnContent("exchange/id 1")).resolves.toEqual(body);

    expect(fetchMock).toHaveBeenCalledWith("/api/exchanges/exchange%2Fid%201/turn-content");
  });

  it("uses a configured base URL without changing endpoint callers", async () => {
    const body = {
      user_text: "show me the thing",
      response_text: "here it is",
      stop_reason: "end_turn",
    };
    const fetchMock = stubFetch(body);
    setApiTransport(createApiTransport({ baseUrl: "http://127.0.0.1:4321/" }));

    await expect(fetchTurnContent("exchange/id 1")).resolves.toEqual(body);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:4321/api/exchanges/exchange%2Fid%201/turn-content",
    );
  });

  it("throws on non OK responses", async () => {
    stubFetch({ detail: "not found" }, 404);

    await expect(fetchTurnContent("missing")).rejects.toThrow(
      "Failed to fetch turn content for missing: 404",
    );
  });
});
