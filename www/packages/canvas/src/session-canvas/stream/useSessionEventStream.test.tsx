import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  installMockTransport,
  jsonResponse,
  makeSessionEvent,
  restoreTransport,
} from "../testUtils";
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
    restoreTransport();
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

    expect(sources[0]?.url).toBe("/v1/sessions/session-1/events/stream?owner=local&last_seq=-1");
    act(() => {
      sources[0]?.onmessage?.(
        new MessageEvent("message", { data: JSON.stringify(makeSessionEvent({ seq: 0 })) }),
      );
    });

    expect(onEvents).toHaveBeenCalledWith([expect.objectContaining({ seq: 0 })]);
  });

  it("closes before reconnecting with the highest observed seq", () => {
    const onEvents = vi.fn();
    renderHook(() =>
      useSessionEventStream({
        enabled: true,
        highestSeq: 1,
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
    expect(sources[1]?.url).toBe("/v1/sessions/session-1/events/stream?owner=local&last_seq=2");
  });

  it("backfills missing seq before dispatching a skipped live event", async () => {
    const onEvents = vi.fn();
    installMockTransport((path) => {
      expect(path).toBe("/v1/sessions/session-1/events?owner=local&limit=500&from_seq=0&to_seq=1");
      return jsonResponse({
        events: [makeSessionEvent({ seq: 0 }), makeSessionEvent({ seq: 1 })],
        nextFromSeq: null,
      });
    });
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
    });

    await act(async () => {});

    expect(onEvents).toHaveBeenCalledWith([
      expect.objectContaining({ seq: 0 }),
      expect.objectContaining({ seq: 1 }),
      expect.objectContaining({ seq: 2 }),
    ]);
  });
});
