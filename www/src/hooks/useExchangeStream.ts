import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { apiUrl } from "../api";
import { useUIStore } from "../stores/uiStore";
import { applyExchangeStreamEvent } from "./exchangeStreamEvents";

export interface ExchangeStreamSourceHandlers {
  onOpen: () => void;
  onError: () => void;
  onMessage: (message: string) => void;
}

export interface ExchangeStreamSource {
  close: () => void;
}

export interface BrowserExchangeStreamSourceOptions {
  baseUrl?: string;
}

export function createBrowserExchangeStreamSource(
  handlers: ExchangeStreamSourceHandlers,
  { baseUrl }: BrowserExchangeStreamSourceOptions = {},
): ExchangeStreamSource {
  const source = new EventSource(apiUrl("/api/stream", baseUrl));
  source.onopen = handlers.onOpen;
  source.onerror = handlers.onError;
  source.onmessage = (event: MessageEvent<string>) => handlers.onMessage(event.data);
  return { close: () => source.close() };
}

export type UseExchangeStreamOptions = BrowserExchangeStreamSourceOptions;

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
      queryClient.invalidateQueries({ queryKey: ["exchanges"] });
    }
    if (connected) hasConnected.current = true;
  }, [connected, queryClient]);

  useEffect(() => {
    const source = createBrowserExchangeStreamSource(
      {
        onOpen: () => setConnected(true),
        onError: () => setConnected(false),
        onMessage: (message) =>
          applyExchangeStreamEvent(message, {
            queryClient,
            setPausedFlow,
            clearPausedFlow,
            setSelectedId,
          }),
      },
      { baseUrl },
    );

    return () => source.close();
  }, [baseUrl, queryClient, setPausedFlow, clearPausedFlow, setSelectedId]);

  return { connected };
}
