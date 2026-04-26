import { useEffect } from "react";
import { ArmToggle } from "./components/ArmToggle";
import { ExchangeDetail } from "./components/ExchangeDetail";
import { ExchangeList } from "./components/ExchangeList";
import { BreakpointEditor } from "./components/editor/BreakpointEditor";
import { ManicureIcon } from "./components/ManicureIcon";
import { RouteRail } from "./components/RouteRail";
import { OverlaysView } from "./components/routes/OverlaysView";
import { RecallView } from "./components/routes/RecallView";
import { TraceView } from "./components/routes/TraceView";
import { useBreakpoint } from "./hooks/useBreakpoint";
import { useExchangeStream } from "./hooks/useExchangeStream";
import { useExchanges } from "./hooks/useExchanges";
import { useMeta } from "./hooks/useMeta";
import { useRouteHotkeys } from "./hooks/useRouteHotkeys";
import { useUIStore } from "./stores/uiStore";

function ConnectionDot({ connected }: { connected: boolean }) {
  return (
    <span
      className={`flex items-center gap-1.5 text-[11px] uppercase tracking-[0.18em] ${
        connected ? "text-sage" : "text-rose"
      }`}
    >
      <span className={`h-1 w-1 rounded-full ${connected ? "bg-sage pulse-dot" : "bg-rose"}`} />
      {connected ? "Live" : "Off"}
    </span>
  );
}

interface AppBarProps {
  connected: boolean;
  mode: "off" | "armed_once";
  onToggleArm: () => void;
  breakpointError: boolean;
  exchangeCount: number;
  includeHistory: boolean;
}

function AppBar({
  connected,
  mode,
  onToggleArm,
  breakpointError,
  exchangeCount,
  includeHistory,
}: AppBarProps) {
  return (
    <>
      <div className="top-highlight relative overflow-hidden flex items-center justify-between gap-4 bg-surface px-6 py-3">
        {/* Brand lockup */}
        <div className="flex items-center gap-3 min-w-0">
          <ManicureIcon className="h-[22px] w-[22px] text-txt shrink-0" />
          <h1 className="text-[14px] font-semibold tracking-[0.22em] text-txt uppercase whitespace-nowrap">
            Manicure
          </h1>
          <span className="text-edge-strong hidden sm:inline">&middot;</span>
          <span className="text-[11px] text-txt-3 tracking-[0.14em] tabular-nums hidden sm:inline">
            v{__MANICURE_VERSION__}
          </span>
        </div>

        {/* Controls cluster */}
        <div className="flex items-center gap-5 shrink-0">
          <div className="hidden md:flex items-center gap-2 text-[11px]">
            <span className="label">{includeHistory ? "Visible" : "Exchanges"}</span>
            <span className="text-[13px] text-txt-2 metric-num">{exchangeCount}</span>
            {includeHistory && <span className="label text-sky">history on</span>}
          </div>
          <span className="hidden md:block h-4 w-px bg-edge" aria-hidden />
          <ConnectionDot connected={connected} />
          <span className="h-4 w-px bg-edge" aria-hidden />
          <ArmToggle mode={mode} onToggle={onToggleArm} error={breakpointError} />
        </div>
      </div>
      <div className="hairline-x" />
    </>
  );
}

export function App() {
  const includeHistory = useUIStore((s) => s.includeHistory);
  const setIncludeHistory = useUIStore((s) => s.setIncludeHistory);
  const { exchanges, trackTree, isLoading } = useExchanges(includeHistory);
  const { meta } = useMeta();
  const { connected } = useExchangeStream();
  const { mode, arm, disarm, error: breakpointError } = useBreakpoint();
  const activeRoute = useUIStore((s) => s.activeRoute);
  const selectedId = useUIStore((s) => s.selectedId);
  const setSelectedId = useUIStore((s) => s.setSelectedId);
  const pausedFlow = useUIStore((s) => s.pausedFlow);
  const clearPausedFlow = useUIStore((s) => s.clearPausedFlow);

  useRouteHotkeys();

  const selectedExchangeVisible =
    selectedId != null && exchanges.some((entry) => entry.id === selectedId);
  const shouldLookupHiddenSelection =
    !includeHistory && selectedId != null && !selectedExchangeVisible;
  const { exchanges: historyExchanges, isLoading: isHistoryLookupLoading } = useExchanges(
    true,
    shouldLookupHiddenSelection,
  );
  const selectedExchangeExistsInHistory =
    selectedId != null && historyExchanges.some((entry) => entry.id === selectedId);
  const selectedExchangeHiddenByFilter =
    shouldLookupHiddenSelection && selectedExchangeExistsInHistory;

  useEffect(() => {
    if (isLoading || !selectedId) return;
    if (selectedExchangeVisible) return;
    if (!includeHistory) {
      if (isHistoryLookupLoading) return;
      if (selectedExchangeExistsInHistory) return;
    }
    setSelectedId(null);
  }, [
    includeHistory,
    isHistoryLookupLoading,
    isLoading,
    selectedExchangeExistsInHistory,
    selectedExchangeVisible,
    selectedId,
    setSelectedId,
  ]);

  const toggleArm = () => (mode === "off" ? arm() : disarm());
  const showEntryPage = !includeHistory && exchanges.length === 0 && pausedFlow == null;

  if (showEntryPage) {
    return (
      <div className="h-screen bg-canvas text-txt relative overflow-hidden">
        <div className="absolute inset-0 flex items-center justify-center text-edge-subtle opacity-30 pointer-events-none">
          <ManicureIcon className="spin-gentle h-[90vh] w-[90vh]" />
        </div>
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-6">
          <div className="flex flex-col items-center gap-3">
            <ManicureIcon className="h-[64px] w-[64px] text-txt shrink-0" />
            <h1 className="text-[14px] font-semibold tracking-[0.18em] text-txt uppercase">
              Manicure
            </h1>
            <span className="label">Waiting for exchanges</span>
          </div>
          <ConnectionDot connected={connected} />
          <div className="flex items-center gap-4">
            <ArmToggle mode={mode} onToggle={toggleArm} error={!!breakpointError} />
            <button
              type="button"
              onClick={() => setIncludeHistory(true)}
              className="btn border border-edge bg-surface px-3.5 py-1.5 text-[12px] font-semibold uppercase tracking-[0.18em] text-txt-3 transition-colors hover:bg-raised hover:text-txt"
            >
              Show history
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen bg-canvas text-txt">
      <div className="frame flex h-full flex-col border-x border-edge">
        <AppBar
          connected={connected}
          mode={mode}
          onToggleArm={toggleArm}
          breakpointError={!!breakpointError}
          exchangeCount={exchanges.length}
          includeHistory={includeHistory}
        />

        <RouteRail />

        {activeRoute === "intercept" ? (
          <div className="flex flex-1 overflow-hidden">
            {/* Left panel */}
            <aside className="flex w-[460px] min-w-[400px] flex-col border-r border-edge">
              <ExchangeList
                exchanges={exchanges}
                trackTree={trackTree}
                currentRunId={meta?.runId ?? null}
                includeHistory={includeHistory}
                onIncludeHistoryChange={setIncludeHistory}
                selectedId={selectedId}
                onSelect={setSelectedId}
              />
            </aside>

            {/* Right panel */}
            <main className="flex-1 overflow-hidden">
              {pausedFlow != null ? (
                <BreakpointEditor
                  key={pausedFlow.flow_id}
                  pausedFlow={pausedFlow}
                  onResolved={clearPausedFlow}
                />
              ) : selectedExchangeVisible && selectedId ? (
                <ExchangeDetail id={selectedId} />
              ) : selectedExchangeHiddenByFilter ? (
                <div className="flex h-full items-center justify-center px-8">
                  <div className="max-w-md border border-edge bg-surface px-5 py-4 text-center">
                    <p className="text-[13px] leading-6 text-txt-2">
                      The selected exchange is outside the live session view. Turn on history to
                      restore that prior-run selection.
                    </p>
                    <button
                      type="button"
                      onClick={() => setIncludeHistory(true)}
                      className="mt-4 btn border border-edge bg-raised px-3.5 py-1.5 text-[12px] font-semibold uppercase tracking-[0.18em] text-txt transition-colors hover:bg-surface"
                    >
                      Show history
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex h-full items-center justify-center">
                  <span className="label">Select an exchange to inspect</span>
                </div>
              )}
            </main>
          </div>
        ) : activeRoute === "overlays" ? (
          <main className="flex-1 overflow-hidden">
            <OverlaysView />
          </main>
        ) : activeRoute === "trace" ? (
          <main className="flex-1 overflow-hidden">
            <TraceView />
          </main>
        ) : (
          <main className="flex-1 overflow-hidden">
            <RecallView />
          </main>
        )}
      </div>
    </div>
  );
}
