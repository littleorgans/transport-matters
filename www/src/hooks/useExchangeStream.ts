import { useCallback, useEffect, useRef, useState } from "react";
import type { IndexEntry, PausedFlow } from "../types";

const MAX_ENTRIES = 500;

export function useExchangeStream(): {
  exchanges: IndexEntry[];
  connected: boolean;
  pausedFlow: PausedFlow | null;
} {
  const [exchanges, setExchanges] = useState<IndexEntry[]>([]);
  const [connected, setConnected] = useState(false);
  const [pausedFlow, setPausedFlow] = useState<PausedFlow | null>(null);
  const sourceRef = useRef<EventSource | null>(null);

  const handleMessage = useCallback((event: MessageEvent<string>) => {
    try {
      const data = JSON.parse(event.data) as Record<string, unknown>;

      if (data.type === "paused") {
        setPausedFlow({
          flow_id: data.flow_id as string,
          ir: data.ir as PausedFlow["ir"],
          audit: (data.audit as PausedFlow["audit"]) ?? null,
          paused_at_ms: data.paused_at_ms as number,
        });
        return;
      }

      if (data.type === "exchange") {
        const entry: IndexEntry = {
          id: data.id as string,
          ts: data.ts as string,
          provider: data.provider as string,
          model: data.model as string,
          path: "",
          req: data.req as IndexEntry["req"],
          res: (data.res as IndexEntry["res"]) ?? null,
          mutated_manually: false,
        };
        setExchanges((prev) => [entry, ...prev].slice(0, MAX_ENTRIES));

        // Clear paused flow if this exchange corresponds to it
        setPausedFlow((current) => {
          if (current !== null && current.flow_id === (data.id as string)) {
            return null;
          }
          return current;
        });
      }
    } catch {
      // Ignore malformed events
    }
  }, []);

  useEffect(() => {
    const source = new EventSource("/api/stream");
    sourceRef.current = source;

    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.onmessage = handleMessage;

    return () => {
      source.close();
      sourceRef.current = null;
    };
  }, [handleMessage]);

  return { exchanges, connected, pausedFlow };
}
