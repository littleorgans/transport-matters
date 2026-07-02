import { useQueryClient } from "@tanstack/react-query";
import {
  apiUrl,
  applyExchangeStreamEvent,
  exchangesPrefix,
  type StreamSideEffects,
} from "@tm/core";
import { useEffect, useRef, useState } from "react";
import { useUIStore } from "../stores/uiStore";

export type UseExchangeStreamOptions = {
  runId: string | null;
  baseUrl?: string;
};

// Binds the core stream primitive's side-effect port to the product uiStore.
// Reads go through getState() at event time, so the object can be a module
// constant without going stale.
const uiStoreSideEffects: StreamSideEffects = {
  getForwardingFlowId: () => useUIStore.getState().forwardingFlowId,
  getPausedFlow: () => useUIStore.getState().pausedFlow,
  getSelectedId: () => useUIStore.getState().selectedId,
  bumpForwardingActivity: () => useUIStore.getState().bumpForwardingActivity(),
  setForwardingFlowId: (id) => useUIStore.getState().setForwardingFlowId(id),
};

/**
 * Browser SSE pump. EventSource construction stays here; shared event
 * application lives in the core exchange-stream primitive, wired to the
 * uiStore through `StreamSideEffects`.
 */
export function useExchangeStream({ runId, baseUrl }: UseExchangeStreamOptions): {
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
    if (runId === null) {
      setConnected(false);
      return;
    }
    const source = new EventSource(apiUrl(`/v1/runs/${encodeURIComponent(runId)}/stream`, baseUrl));
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    source.onmessage = (event: MessageEvent<string>) =>
      applyExchangeStreamEvent(event.data, {
        runId,
        queryClient,
        setPausedFlow,
        clearPausedFlow,
        setSelectedId,
        sideEffects: uiStoreSideEffects,
      });

    return () => source.close();
  }, [baseUrl, runId, queryClient, setPausedFlow, clearPausedFlow, setSelectedId]);

  return { connected };
}
