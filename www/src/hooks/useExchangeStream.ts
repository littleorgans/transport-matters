import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useUIStore } from "../stores/uiStore";
import type { IndexEntry, PausedFlow } from "../types";

const MAX_ENTRIES = 500;

/**
 * Pure SSE pump: manages the EventSource connection and pushes incoming
 * events into the query cache (exchanges) or Zustand store (pausedFlow).
 * Owns no query state of its own.
 */
export function useExchangeStream(): { connected: boolean } {
  const [connected, setConnected] = useState(false);
  const queryClient = useQueryClient();
  const setPausedFlow = useUIStore((s) => s.setPausedFlow);
  const clearPausedFlow = useUIStore((s) => s.clearPausedFlow);

  useEffect(() => {
    const source = new EventSource("/api/stream");

    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.onmessage = (event: MessageEvent<string>) => {
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
            pipeline: (data.pipeline as IndexEntry["pipeline"]) ?? null,
            res: (data.res as IndexEntry["res"]) ?? null,
            mutated_manually: false,
          };
          queryClient.setQueryData<IndexEntry[]>(["exchanges"], (prev = []) =>
            [entry, ...prev].slice(0, MAX_ENTRIES),
          );
          // Secondary clear: if SSE delivers the matching exchange, also clear the
          // overlay. Primary clear is onResolved in BreakpointEditor after mutation.
          const current = useUIStore.getState().pausedFlow;
          if (current?.flow_id === (data.id as string)) {
            clearPausedFlow();
          }
        }
      } catch {
        // Ignore malformed events
      }
    };

    return () => source.close();
  }, [queryClient, setPausedFlow, clearPausedFlow]);

  return { connected };
}
