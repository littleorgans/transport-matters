import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { apiUrl } from "../api";
import { exchangesPrefix } from "../lib/queryKeys";
import { useUIStore } from "../stores/uiStore";
import { applyExchangeStreamEvent } from "./exchangeStreamEvents";

export type UseExchangeStreamOptions = {
  baseUrl?: string;
};

/**
 * Browser SSE pump. EventSource construction stays here; shared event
 * application lives in exchangeStreamEvents.
 */
export function useExchangeStream({ baseUrl }: UseExchangeStreamOptions = {}): {
  connected: boolean;
} {
  const [connected, setConnected] = useState(false);
  const queryClient = useQueryClient();
  const setPausedFlow = useUIStore((s) => s.setPausedFlow);
  const clearPausedFlow = useUIStore((s) => s.clearPausedFlow);
  const setSelectedId = useUIStore((s) => s.setSelectedId);

  // Backfill exchanges on SSE reconnect to cover any gap during disconnect
  const hasConnected = useRef(false);
  useEffect(() => {
    if (connected && hasConnected.current) {
      queryClient.invalidateQueries({ queryKey: exchangesPrefix });
    }
    if (connected) hasConnected.current = true;
  }, [connected, queryClient]);

  useEffect(() => {
    const source = new EventSource(apiUrl("/api/stream", baseUrl));
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.onmessage = (event: MessageEvent<string>) =>
      applyExchangeStreamEvent(event.data, {
        queryClient,
        setPausedFlow,
        clearPausedFlow,
        setSelectedId,
      });

    return () => source.close();
  }, [baseUrl, queryClient, setPausedFlow, clearPausedFlow, setSelectedId]);

  return { connected };
}
