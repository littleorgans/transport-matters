import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useUIStore } from "../stores/uiStore";
import { applyExchangeStreamEvent } from "./exchangeStreamEvents";

interface ExchangeStreamSourceHandlers {
  onOpen: () => void;
  onError: () => void;
  onMessage: (message: string) => void;
}

interface ExchangeStreamSource {
  close: () => void;
}

function createBrowserExchangeStreamSource(
  handlers: ExchangeStreamSourceHandlers,
): ExchangeStreamSource {
  const source = new EventSource("/api/stream");
  source.onopen = handlers.onOpen;
  source.onerror = handlers.onError;
  source.onmessage = (event: MessageEvent<string>) => handlers.onMessage(event.data);
  return { close: () => source.close() };
}

/**
 * Browser SSE pump. EventSource construction stays here; shared event
 * application lives in exchangeStreamEvents.
 */
export function useExchangeStream(): { connected: boolean } {
  const [connected, setConnected] = useState(false);
  const queryClient = useQueryClient();
  const setPausedFlow = useUIStore((s) => s.setPausedFlow);
  const clearPausedFlow = useUIStore((s) => s.clearPausedFlow);
  const setSelectedId = useUIStore((s) => s.setSelectedId);

  // Backfill exchanges on SSE reconnect to cover any gap during disconnect
  const hasConnected = useRef(false);
  useEffect(() => {
    if (connected && hasConnected.current) {
      queryClient.invalidateQueries({ queryKey: ["exchanges"] });
    }
    if (connected) hasConnected.current = true;
  }, [connected, queryClient]);

  useEffect(() => {
    const source = createBrowserExchangeStreamSource({
      onOpen: () => setConnected(true),
      onError: () => setConnected(false),
      onMessage: (message) =>
        applyExchangeStreamEvent(message, {
          queryClient,
          setPausedFlow,
          clearPausedFlow,
          setSelectedId,
        }),
    });

    return () => source.close();
  }, [queryClient, setPausedFlow, clearPausedFlow, setSelectedId]);

  return { connected };
}
