import { useEffect, useRef, useState } from "react";
import type { SessionEventView } from "../api/sessionEvents";
import { listSessionEvents, sessionEventsStreamUrl } from "../api/sessionEvents";

export interface UseSessionEventStreamArgs {
  enabled: boolean;
  sessionId: string;
  owner: "local";
  highestSeq: number;
  onEvents(events: SessionEventView[]): void;
  baseUrl?: string;
}

const RECONNECT_DELAY_MS = 1_000;

export function useSessionEventStream({
  enabled,
  sessionId,
  owner,
  highestSeq,
  onEvents,
  baseUrl,
}: UseSessionEventStreamArgs): { connected: boolean } {
  const [connected, setConnected] = useState(false);
  const lastSeqRef = useRef(highestSeq);
  const onEventsRef = useRef(onEvents);

  useEffect(() => {
    lastSeqRef.current = highestSeq;
  }, [highestSeq]);

  useEffect(() => {
    onEventsRef.current = onEvents;
  }, [onEvents]);

  useEffect(() => {
    if (!enabled) return undefined;
    let source: EventSource | null = null;
    let reconnectTimer: number | null = null;
    let closed = false;

    async function dispatchParsedEvent(parsed: SessionEventView) {
      const previousHighestSeq = lastSeqRef.current;
      if (closed || parsed.seq <= previousHighestSeq) return;
      if (parsed.seq > previousHighestSeq + 1) {
        await dispatchGapBackfill(parsed, previousHighestSeq);
        return;
      }
      lastSeqRef.current = Math.max(lastSeqRef.current, parsed.seq);
      onEventsRef.current([parsed]);
    }

    async function dispatchGapBackfill(parsed: SessionEventView, previousHighestSeq: number) {
      try {
        const backfill = await listSessionEvents({
          fromSeq: previousHighestSeq + 1,
          owner,
          sessionId,
          toSeq: parsed.seq - 1,
        });
        if (closed) return;
        const events = [...backfill.events, parsed];
        lastSeqRef.current = highestEventSeq(events, previousHighestSeq);
        onEventsRef.current(events);
        setConnected(true);
      } catch {
        if (closed) return;
        lastSeqRef.current = Math.max(lastSeqRef.current, parsed.seq);
        onEventsRef.current([parsed]);
      }
    }

    function connect() {
      if (typeof EventSource === "undefined") return;
      source?.close();
      source = new EventSource(
        sessionEventsStreamUrl(sessionId, owner, lastSeqRef.current, baseUrl),
      );
      source.onopen = () => setConnected(true);
      source.onerror = () => {
        setConnected(false);
        source?.close();
        if (!closed) reconnectTimer = window.setTimeout(connect, RECONNECT_DELAY_MS);
      };
      source.onmessage = (event: MessageEvent<string>) => {
        const parsed = parseEventMessage(event.data);
        if (!parsed) return;
        void dispatchParsedEvent(parsed);
      };
    }

    connect();
    return () => {
      closed = true;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      source?.close();
      setConnected(false);
    };
  }, [baseUrl, enabled, owner, sessionId]);

  return { connected };
}

function parseEventMessage(data: string): SessionEventView | null {
  try {
    const parsed = JSON.parse(data) as SessionEventView;
    return typeof parsed.seq === "number" ? parsed : null;
  } catch {
    return null;
  }
}

function highestEventSeq(events: readonly SessionEventView[], fallback: number): number {
  return events.reduce((highest, event) => Math.max(highest, event.seq), fallback);
}
