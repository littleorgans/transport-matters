import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { exchangesKey } from "../lib/queryKeys";
import type { IndexEntry } from "../types";
import { useExchangeStream } from "./useExchangeStream";
import { getMockSource, makeWrapper } from "./useExchangeStream.testSupport";

describe("useExchangeStream browser source", () => {
  it("keeps EventSource lifecycle and messages behind the hook", () => {
    const { qc, wrapper } = makeWrapper();
    const { result, unmount } = renderHook(() => useExchangeStream({ runId: "run-current" }), {
      wrapper,
    });
    const source = getMockSource();

    expect(source.url).toBe("/v1/runs/run-current/stream");
    expect(result.current.connected).toBe(false);

    act(() => source.onopen?.());
    expect(result.current.connected).toBe(true);

    act(() => source.onerror?.());
    expect(result.current.connected).toBe(false);

    act(() =>
      source.onmessage?.(
        new MessageEvent("message", {
          data: JSON.stringify({
            type: "exchange",
            id: "stream-source-message",
            ts: "2026-01-01T00:00:00Z",
            provider: "codex",
            model: "gpt-5-codex",
            req: { total_chars: 1 },
          }),
        }),
      ),
    );
    expect(qc.getQueryData<IndexEntry[]>(exchangesKey("run-current"))?.[0]?.id).toBe(
      "stream-source-message",
    );

    unmount();
    expect(source.close).toHaveBeenCalled();
  });

  it("constructs the browser stream from a configured API base URL", () => {
    renderHook(
      () => useExchangeStream({ runId: "run-current", baseUrl: "http://127.0.0.1:4321/" }),
      {
        wrapper: makeWrapper().wrapper,
      },
    );

    expect(getMockSource().url).toBe("http://127.0.0.1:4321/v1/runs/run-current/stream");
  });
});
