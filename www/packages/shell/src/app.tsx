import { useMeta } from "@tm/core";
import type { ExchangeTrackStub, PausedFlow } from "@tm/core/types/exchanges";
import { useEffect, useMemo } from "react";
import { exchangeListSessionKey } from "./components/ExchangeList";
import { useBreakpoint } from "./hooks/useBreakpoint";
import { useExchangeStream } from "./hooks/useExchangeStream";
import { useExchanges } from "./hooks/useExchanges";
import { useRouteHotkeys } from "./hooks/useRouteHotkeys";
import { RouteLayout } from "./routeLayout";
import { useUIStore } from "./stores/uiStore";

const EMPTY_COLLAPSED_TRACK_IDS: string[] = [];

function pendingTrackStubsForPausedFlow(pausedFlow: PausedFlow | null): ExchangeTrackStub[] {
  if (
    pausedFlow?.track_role !== "subagent" ||
    !pausedFlow.track_id ||
    !pausedFlow.parent_track_id ||
    !pausedFlow.spawn_anchor?.track_spawn_exchange_id
  ) {
    return [];
  }
  return [
    {
      track_id: pausedFlow.track_id,
      parent_track_id: pausedFlow.parent_track_id,
      track_display_name: pausedFlow.track_display_name ?? null,
      track_role: "subagent",
      status: "pending",
      spawn_anchor: pausedFlow.spawn_anchor,
    },
  ];
}

export function BrowserAppShell() {
  const includeHistory = useUIStore((s) => s.includeHistory);
  const setIncludeHistory = useUIStore((s) => s.setIncludeHistory);
  const pausedFlow = useUIStore((s) => s.pausedFlow);
  const activeRoute = useUIStore((s) => s.activeRoute);
  const setActiveRoute = useUIStore((s) => s.setActiveRoute);
  const selectedId = useUIStore((s) => s.selectedId);
  const setSelectedId = useUIStore((s) => s.setSelectedId);
  const clearPausedFlow = useUIStore((s) => s.clearPausedFlow);
  const pendingTrackStubs = useMemo(() => pendingTrackStubsForPausedFlow(pausedFlow), [pausedFlow]);
  const { meta } = useMeta();
  const runId = meta?.runId ?? null;
  const { exchanges, trackTree, isLoading } = useExchanges(runId, true, pendingTrackStubs);
  const collapseSessionKey = exchangeListSessionKey(runId, exchanges);
  const collapsedTrackIds = useUIStore(
    (s) => s.collapsedTrackIdsBySession[collapseSessionKey] ?? EMPTY_COLLAPSED_TRACK_IDS,
  );
  const toggleCollapsedTrack = useUIStore((s) => s.toggleCollapsedTrack);
  const { connected } = useExchangeStream({ runId });
  const { mode, arm, disarm, error: breakpointError } = useBreakpoint();

  useRouteHotkeys();

  const selectedExchangeVisible =
    selectedId != null && exchanges.some((entry) => entry.id === selectedId);
  const shouldLookupHiddenSelection =
    !includeHistory && selectedId != null && !selectedExchangeVisible;
  const { exchanges: historyExchanges, isLoading: isHistoryLookupLoading } = useExchanges(
    runId,
    shouldLookupHiddenSelection,
  );
  const selectedExchangeExistsInHistory =
    selectedId != null && historyExchanges.some((entry) => entry.id === selectedId);
  const selectedExchangeHiddenByFilter =
    shouldLookupHiddenSelection && selectedExchangeExistsInHistory;

  useEffect(() => {
    if (runId === null || isLoading || !selectedId) return;
    if (selectedExchangeVisible) return;
    if (!includeHistory) {
      if (isHistoryLookupLoading) return;
      if (selectedExchangeExistsInHistory) return;
    }
    setSelectedId(null);
  }, [
    includeHistory,
    runId,
    isHistoryLookupLoading,
    isLoading,
    selectedExchangeExistsInHistory,
    selectedExchangeVisible,
    selectedId,
    setSelectedId,
  ]);

  const toggleArm = () => (mode === "off" ? arm() : disarm());

  return (
    <RouteLayout
      connected={connected}
      mode={mode}
      onToggleArm={toggleArm}
      breakpointError={!!breakpointError}
      exchanges={exchanges}
      trackTree={trackTree}
      metaRunId={meta?.runId ?? null}
      includeHistory={includeHistory}
      onIncludeHistoryChange={setIncludeHistory}
      selectedId={selectedId}
      onSelectExchange={setSelectedId}
      pausedFlow={pausedFlow}
      onPausedFlowResolved={clearPausedFlow}
      activeRoute={activeRoute}
      onActiveRouteChange={setActiveRoute}
      collapsedTrackIds={collapsedTrackIds}
      onToggleCollapsedTrack={(trackId) => toggleCollapsedTrack(collapseSessionKey, trackId)}
      selectedExchangeHiddenByFilter={selectedExchangeHiddenByFilter}
    />
  );
}

export function App() {
  return <BrowserAppShell />;
}
