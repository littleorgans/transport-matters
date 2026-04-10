import { useCallback, useEffect, useRef, useState } from "react";
import type { IndexEntry } from "../types";

const MAX_ENTRIES = 500;

export function useExchangeStream(): {
  exchanges: IndexEntry[];
  connected: boolean;
} {
  const [exchanges, setExchanges] = useState<IndexEntry[]>([]);
  const [connected, setConnected] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);

  const handleMessage = useCallback((event: MessageEvent<string>) => {
    try {
      const data = JSON.parse(event.data) as Record<string, unknown>;
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

  return { exchanges, connected };
}
