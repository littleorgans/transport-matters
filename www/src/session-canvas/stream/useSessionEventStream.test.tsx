import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { makeSessionEvent } from "../testUtils";
import { useSessionEventStream } from "./useSessionEventStream";

const sources: MockEventSource[] = [];

class MockEventSource {
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  close = vi.fn();
  constructor(public readonly url: string) {
    sources.push(this);
  }
}

describe("useSessionEventStream", () => {
  beforeEach(() => {
    sources.length = 0;
    vi.useFakeTimers();
    vi.stubGlobal("EventSource", MockEventSource);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("opens one stream and dispatches parsed events", () => {
    const onEvents = vi.fn();
    renderHook(() =>
      useSessionEventStream({
        enabled: true,
        highestSeq: -1,
        onEvents,
        owner: "local",
        sessionId: "session-1",
      }),
    );

    expect(sources[0]?.url).toBe("/api/sessions/session-1/events/stream?owner=local&last_seq=-1");
    act(() => {
      sources[0]?.onmessage?.(
        new MessageEvent("message", { data: JSON.stringify(makeSessionEvent({ seq: 1 })) }),
      );
    });

    expect(onEvents).toHaveBeenCalledWith([expect.objectContaining({ seq: 1 })]);
  });

  it("closes before reconnecting with the highest observed seq", () => {
    const onEvents = vi.fn();
    renderHook(() =>
      useSessionEventStream({
        enabled: true,
        highestSeq: -1,
        onEvents,
        owner: "local",
        sessionId: "session-1",
      }),
    );

    act(() => {
      sources[0]?.onmessage?.(
        new MessageEvent("message", { data: JSON.stringify(makeSessionEvent({ seq: 2 })) }),
      );
      sources[0]?.onerror?.();
      vi.advanceTimersByTime(1_000);
    });

    expect(sources[0]?.close).toHaveBeenCalled();
    expect(sources[1]?.url).toBe("/api/sessions/session-1/events/stream?owner=local&last_seq=2");
  });
});
