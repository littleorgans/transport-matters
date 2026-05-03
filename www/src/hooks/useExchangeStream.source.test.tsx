import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useExchangeStream } from "./useExchangeStream";
import { getMockSource, makeWrapper } from "./useExchangeStream.testSupport";

describe("useExchangeStream browser source", () => {
  it("keeps EventSource lifecycle behind the hook", () => {
    const { result, unmount } = renderHook(() => useExchangeStream(), {
      wrapper: makeWrapper().wrapper,
    });
    const source = getMockSource();

    expect(source.url).toBe("/api/stream");
    expect(result.current.connected).toBe(false);

    act(() => source.onopen?.());
    expect(result.current.connected).toBe(true);

    act(() => source.onerror?.());
    expect(result.current.connected).toBe(false);

    unmount();
    expect(source.close).toHaveBeenCalled();
  });
});
