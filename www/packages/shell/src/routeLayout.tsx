import { ArmToggle } from "./components/ArmToggle";
import { ExchangeDetail } from "./components/ExchangeDetail";
import { ExchangeList } from "./components/ExchangeList";
import { BreakpointEditor } from "./components/editor/BreakpointEditor";
import { RouteRail } from "./components/RouteRail";
import { OverlaysView } from "./components/routes/OverlaysView";
import { RecallView } from "./components/routes/RecallView";
import { RouteAtmosphere } from "./components/routes/RouteAtmosphere";
import { TraceView } from "./components/routes/TraceView";
import { TransportMattersIcon } from "./components/TransportMattersIcon";
import type { Route } from "./stores/uiStore";
import type { ExchangeTrack, IndexEntry, PausedFlow } from "./types";

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
        <div className="flex items-center gap-3 min-w-0">
          <TransportMattersIcon className="h-[22px] w-[22px] text-txt shrink-0" />
          <h1 className="text-[14px] font-semibold tracking-[0.22em] text-txt uppercase whitespace-nowrap">
            Transport Matters
          </h1>
          <span className="text-edge-strong hidden sm:inline">&middot;</span>
          <span className="text-[11px] text-txt-3 tracking-[0.14em] tabular-nums hidden sm:inline">
            v{__TRANSPORT_MATTERS_VERSION__}
          </span>
        </div>

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

interface WaitingScreenProps {
  connected: boolean;
  mode: "off" | "armed_once";
  onToggleArm: () => void;
  breakpointError: boolean;
  onShowHistory: () => void;
}

function WaitingScreen({
  connected,
  mode,
  onToggleArm,
  breakpointError,
  onShowHistory,
}: WaitingScreenProps) {
  return (
    <RouteAtmosphere fullScreen>
      <div className="flex flex-col items-center gap-3">
        <TransportMattersIcon className="h-[64px] w-[64px] text-txt shrink-0" />
        <h1 className="text-[14px] font-semibold tracking-[0.18em] text-txt uppercase">
          Transport Matters
        </h1>
        <span className="label">Waiting for exchanges</span>
      </div>
      <ConnectionDot connected={connected} />
      <div className="flex items-center gap-4">
        <ArmToggle mode={mode} onToggle={onToggleArm} error={breakpointError} />
        <button
          type="button"
          onClick={onShowHistory}
          className="btn border border-edge bg-surface px-3.5 py-1.5 text-[12px] font-semibold uppercase tracking-[0.18em] text-txt-3 transition-colors hover:bg-raised hover:text-txt"
        >
          Show history
        </button>
      </div>
    </RouteAtmosphere>
  );
}

export interface RouteLayoutProps {
  connected: boolean;
  mode: "off" | "armed_once";
  onToggleArm: () => void;
  breakpointError: boolean;
  exchanges: IndexEntry[];
  trackTree: ExchangeTrack[];
  metaRunId: string | null;
  includeHistory: boolean;
  onIncludeHistoryChange: (value: boolean) => void;
  selectedId: string | null;
  onSelectExchange: (id: string | null) => void;
  pausedFlow: PausedFlow | null;
  onPausedFlowResolved: () => void;
  activeRoute: Route;
  onActiveRouteChange: (route: Route) => void;
  collapsedTrackIds: readonly string[];
  onToggleCollapsedTrack: (trackId: string) => void;
  selectedExchangeHiddenByFilter?: boolean;
}

function InterceptRoute({
  exchanges,
  trackTree,
  metaRunId,
  includeHistory,
  onIncludeHistoryChange,
  selectedId,
  onSelectExchange,
  collapsedTrackIds,
  onToggleCollapsedTrack,
  pausedFlow,
  onPausedFlowResolved,
  selectedExchangeHiddenByFilter,
}: Pick<
  RouteLayoutProps,
  | "exchanges"
  | "trackTree"
  | "metaRunId"
  | "includeHistory"
  | "onIncludeHistoryChange"
  | "selectedId"
  | "onSelectExchange"
  | "collapsedTrackIds"
  | "onToggleCollapsedTrack"
  | "pausedFlow"
  | "onPausedFlowResolved"
  | "selectedExchangeHiddenByFilter"
>) {
  const selectedExchangeVisible =
    selectedId != null && exchanges.some((entry) => entry.id === selectedId);

  return (
    <div className="flex flex-1 overflow-hidden">
      <aside className="flex w-[460px] min-w-[400px] flex-col border-r border-edge">
        <ExchangeList
          exchanges={exchanges}
          trackTree={trackTree}
          currentRunId={metaRunId}
          includeHistory={includeHistory}
          onIncludeHistoryChange={onIncludeHistoryChange}
          selectedId={selectedId}
          onSelect={onSelectExchange}
          collapsedTrackIds={collapsedTrackIds}
          onToggleCollapsedTrack={onToggleCollapsedTrack}
        />
      </aside>

      <main className="flex-1 overflow-hidden">
        {pausedFlow != null ? (
          <BreakpointEditor
            key={pausedFlow.flow_id}
            pausedFlow={pausedFlow}
            onResolved={onPausedFlowResolved}
          />
        ) : selectedExchangeVisible && selectedId && metaRunId ? (
          <ExchangeDetail id={selectedId} runId={metaRunId} />
        ) : selectedExchangeHiddenByFilter ? (
          <div className="flex h-full items-center justify-center px-8">
            <div className="max-w-md border border-edge bg-surface px-5 py-4 text-center">
              <p className="text-[13px] leading-6 text-txt-2">
                The selected exchange is outside the live session view. Turn on history to restore
                that prior-run selection.
              </p>
              <button
                type="button"
                onClick={() => onIncludeHistoryChange(true)}
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
  );
}

export function RouteLayout(props: RouteLayoutProps) {
  const showEntryPage =
    !props.includeHistory && props.exchanges.length === 0 && props.pausedFlow == null;

  if (showEntryPage) {
    return (
      <WaitingScreen
        connected={props.connected}
        mode={props.mode}
        onToggleArm={props.onToggleArm}
        breakpointError={props.breakpointError}
        onShowHistory={() => props.onIncludeHistoryChange(true)}
      />
    );
  }

  return (
    <div className="h-screen bg-canvas text-txt">
      <div className="frame flex h-full flex-col border-x border-edge">
        <AppBar
          connected={props.connected}
          mode={props.mode}
          onToggleArm={props.onToggleArm}
          breakpointError={props.breakpointError}
          exchangeCount={props.exchanges.length}
          includeHistory={props.includeHistory}
        />

        <RouteRail
          activeRoute={props.activeRoute}
          onActiveRouteChange={props.onActiveRouteChange}
        />

        {props.activeRoute === "intercept" ? (
          <InterceptRoute {...props} />
        ) : props.activeRoute === "overlays" ? (
          <main className="flex-1 overflow-hidden">
            <OverlaysView />
          </main>
        ) : props.activeRoute === "trace" ? (
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
