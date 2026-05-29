import { useEffect, useState } from "react";
import { useTurnContent } from "../hooks/useTurnContent";
import { agentRailStyle, type DepthRailStyle } from "../lib/agentPalette";
import { contextTokens, displayModel } from "../lib/formatting";
import type { CodexTurnListSummary, IndexEntry } from "../types";
import { ExchangePreview } from "./ExchangePreview";

interface ExchangeTurnCardProps {
  entry: IndexEntry;
  depth: number;
  isHistorical: boolean;
  isSelected: boolean;
  previewWaiting: boolean;
  index: number;
  offsetTop: number;
  turnSequence?: number;
  onSelect: (id: string) => void;
}

interface PanelMetric {
  key: string;
  label: string;
  value: string;
}

const TOKEN_SEGMENTS = [
  { delay: "0ms", key: "segment-00" },
  { delay: "55ms", key: "segment-01" },
  { delay: "110ms", key: "segment-02" },
  { delay: "165ms", key: "segment-03" },
  { delay: "220ms", key: "segment-04" },
  { delay: "275ms", key: "segment-05" },
  { delay: "330ms", key: "segment-06" },
  { delay: "385ms", key: "segment-07" },
  { delay: "440ms", key: "segment-08" },
  { delay: "495ms", key: "segment-09" },
] as const;

function formatRelativeTime(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return new Date(ts).toLocaleDateString();
}

function formatElapsedTime(ts: string): string {
  const diff = Math.max(0, Date.now() - new Date(ts).getTime());
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

function useElapsedTick(active: boolean): void {
  const [, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);
}

function formatCount(value: number): string {
  return value.toLocaleString();
}

function formatTurn(turn?: CodexTurnListSummary | null, fallbackIndex?: number): string {
  if (turn) return String(turn.turn_index).padStart(3, "0");
  if (fallbackIndex != null) return String(fallbackIndex).padStart(3, "0");
  return "REQ";
}

function TurnValue({
  turn,
  fallbackIndex,
}: {
  turn?: CodexTurnListSummary | null;
  fallbackIndex?: number;
}) {
  const value = formatTurn(turn, fallbackIndex);
  if (value === "REQ") return <>{value}</>;
  const digits = [
    { digit: value[0], key: "hundreds" },
    { digit: value[1], key: "tens" },
    { digit: value[2], key: "ones" },
  ];
  return (
    <>
      {digits.map(({ digit, key }) => (
        <span key={key} className="text-txt-3">
          {digit ?? ""}
        </span>
      ))}
    </>
  );
}

function cardBorderClass(entry: IndexEntry, isOpen: boolean): string {
  if (isOpen) return "border-amber/45 group-hover:border-amber/65";
  const turnStatus = entry.codex_turn?.status;
  if (turnStatus === "completed") return "border-sage/30 group-hover:border-sage/50";
  if (turnStatus === "failed") return "border-rose/30 group-hover:border-rose/50";
  if (turnStatus === "interrupted") return "border-lavender/30 group-hover:border-lavender/50";
  return "border-edge-strong group-hover:border-edge";
}

function transportTitle(entry: IndexEntry): string | undefined {
  const turn = entry.codex_turn;
  if (!turn) {
    return entry.provider === "codex" ? "request | waiting for Codex transport" : undefined;
  }
  const parts = [
    `turn ${turn.turn_index}`,
    `frames ${turn.message_range_start}->${turn.message_range_end}`,
    turn.terminal_cause?.replaceAll("_", " "),
    turn.stop_reason,
  ].filter(Boolean);
  if (turn.status === "open") parts.push("waiting for Codex transport");
  return parts.join(" | ");
}

function previewTransportTitle(entry: IndexEntry): string {
  const turn = entry.codex_turn;
  const turnLabel = turn ? `turn ${turn.turn_index}` : "request";
  return `${turnLabel} | previewing open waiting transport`;
}

function isPendingCodexTransport(entry: IndexEntry): boolean {
  if (entry.provider !== "codex") {
    return false;
  }
  if (entry.codex_turn?.status === "open") {
    return true;
  }
  return entry.codex_turn == null && entry.res === null;
}

function isPendingClaudeTransport(entry: IndexEntry): boolean {
  return entry.provider !== "codex" && !entry.codex_turn && entry.res === null;
}

function panelMetrics(entry: IndexEntry): PanelMetric[] {
  const res = entry.res;
  if (res === null) {
    return [
      { key: "input", label: "Input", value: "—" },
      { key: "output", label: "Output", value: "—" },
      { key: "total", label: "Total", value: "—" },
    ];
  }
  return [
    { key: "input", label: "Input", value: formatCount(res.input_tokens) },
    { key: "output", label: "Output", value: formatCount(res.output_tokens) },
    { key: "total", label: "Total", value: formatCount(contextTokens(res)) },
  ];
}

function metricLabel(metrics: PanelMetric[]): string {
  return metrics.map((metric) => `${metric.label}: ${metric.value}`).join(", ");
}

function PanelMetricValue({ metric }: { metric: PanelMetric }) {
  const isZero = metric.value === "0" || metric.value === "—";
  return <span className={isZero ? "text-txt-3" : "text-txt"}>{metric.value}</span>;
}

function TurnContentValue({
  text,
  stopReason,
  isLoading,
}: {
  text?: string | null;
  stopReason?: string | null;
  isLoading: boolean;
}) {
  if (isLoading) {
    return <span className="min-w-0 text-[13px] leading-snug text-txt-3">…</span>;
  }
  if (!text && stopReason) {
    return (
      <span className="min-w-0 text-[13px] leading-snug text-txt-3">
        —<span className="ml-2 text-[11px] uppercase">· {stopReason}</span>
      </span>
    );
  }
  if (!text) {
    return <span className="min-w-0 text-[13px] leading-snug text-txt-3">—</span>;
  }
  return <ExchangePreview text={text} stopReason={stopReason} />;
}

function SettledTurnContentPreview({ entryId }: { entryId: string }) {
  const { data, isLoading } = useTurnContent(entryId);
  return (
    <span className="grid min-w-0 grid-cols-2 border-b border-edge">
      <span className="min-w-0 border-r border-edge px-4 py-3">
        <TurnContentValue text={data?.user_text} isLoading={isLoading} />
      </span>
      <span className="min-w-0 px-4 py-3">
        <TurnContentValue
          text={data?.response_text}
          stopReason={data?.stop_reason}
          isLoading={isLoading}
        />
      </span>
    </span>
  );
}

function WaitingTransportStrip({
  entry,
  isCodexPending,
  previewWaiting,
}: {
  entry: IndexEntry;
  isCodexPending: boolean;
  previewWaiting: boolean;
}) {
  return (
    <span
      title={previewWaiting ? previewTransportTitle(entry) : transportTitle(entry)}
      className="flex items-center gap-3 border-b border-edge px-4 py-3"
    >
      <span
        data-testid={`exchange-token-activity-${entry.id}`}
        className="grid w-full grid-cols-[repeat(10,minmax(0,1fr))] gap-1"
        aria-hidden
      >
        {TOKEN_SEGMENTS.map((segment) => (
          <span
            key={`${entry.id}-${segment.key}`}
            className="token-segment h-3 border border-edge-strong bg-surface"
            style={{ animationDelay: segment.delay }}
          />
        ))}
      </span>
      {isCodexPending && entry.codex_turn && (
        <span className="label shrink-0 text-[11px] text-txt-3">
          {entry.codex_turn.message_range_start}→{entry.codex_turn.message_range_end}
        </span>
      )}
    </span>
  );
}

export function ExchangeTurnCard({
  entry,
  depth,
  isHistorical,
  isSelected,
  previewWaiting,
  index,
  offsetTop,
  turnSequence,
  onSelect,
}: ExchangeTurnCardProps) {
  const isClaudePending = isPendingClaudeTransport(entry);
  const isCodexPending = isPendingCodexTransport(entry);
  const isOpen = previewWaiting || isCodexPending || isClaudePending;
  useElapsedTick(isClaudePending);
  const isSubagent = depth > 0;
  const metrics = panelMetrics(entry);
  const borderClass = isSelected ? "border-accent row-selected" : cardBorderClass(entry, isOpen);
  const style: DepthRailStyle = {
    transform: `translateY(${offsetTop}px)`,
    "--track-depth": String(depth),
    ...agentRailStyle(entry.track_id),
  };

  return (
    <button
      type="button"
      data-testid={`exchange-row-${entry.id}`}
      data-index={index}
      data-depth={depth}
      onClick={() => onSelect(entry.id)}
      className={`group absolute left-0 right-0 top-0 min-h-[250px] cursor-pointer text-left text-txt-2 ${
        isSubagent ? "grid grid-cols-[1px_8px_52px_minmax(0,1fr)]" : ""
      }`}
      style={style}
    >
      {isSubagent && <span aria-hidden />}
      {isSubagent && (
        <span
          className="min-h-[250px] bg-[var(--agent-rail)] shadow-[0_0_22px_rgb(var(--agent-rail-rgb)/0.32)]"
          aria-hidden
        />
      )}
      {isSubagent && (
        <span
          aria-hidden
          className="flex min-h-[250px] items-start justify-center border-y border-r border-[rgb(var(--agent-rail-rgb)/0.25)] bg-[linear-gradient(180deg,#101112,#080909)] pt-[76px] shadow-[inset_0_1px_0_rgb(var(--highlight-rgb)/0.05)]"
        >
          <span className="label text-[11px] text-[var(--agent-rail)]">Sub</span>
        </span>
      )}
      <span
        className={`relative grid min-h-[250px] min-w-0 grid-rows-[58px_140px_48px] overflow-hidden border bg-[linear-gradient(180deg,#101112,#070707)] shadow-[inset_0_1px_0_rgb(var(--highlight-rgb)/0.07),inset_0_-22px_45px_rgb(var(--shadow-rgb)/0.35)] transition-colors duration-150 ${borderClass} ${isSubagent ? "min-h-[250px]" : ""}`}
      >
        {isOpen && (
          <span className="absolute inset-x-0 top-0 h-px overflow-hidden bg-amber/20">
            <span className="transport-scan block h-full w-1/3 bg-amber/85" />
          </span>
        )}

        <span className="flex items-center gap-3 border-b border-edge px-4">
          <span className="metric-num shrink-0 text-[14px] text-txt-2">
            <TurnValue turn={entry.codex_turn} fallbackIndex={turnSequence} />
          </span>
          <span className="label min-w-0 flex-1 truncate text-[11px] font-normal uppercase tracking-widest text-txt-3">
            {displayModel(entry.provider, entry.model)}
            {isHistorical && (
              <span
                className="chip ml-2 px-2 py-1 text-[9px] text-sky"
                title={entry.run_id ? `run ${entry.run_id}` : "Captured before this run"}
              >
                prior
              </span>
            )}
          </span>
          <span
            data-testid={`exchange-time-${entry.id}`}
            className="metric-num shrink-0 border border-edge-strong bg-canvas/35 px-3 py-1.5 text-[12px] uppercase text-txt-2"
          >
            {isClaudePending ? formatElapsedTime(entry.ts) : formatRelativeTime(entry.ts)}
          </span>
        </span>

        {isOpen ? (
          <WaitingTransportStrip
            entry={entry}
            isCodexPending={isCodexPending}
            previewWaiting={previewWaiting}
          />
        ) : (
          <SettledTurnContentPreview entryId={entry.id} />
        )}

        <span
          data-testid={`exchange-metrics-${entry.id}`}
          className="grid min-w-0 grid-cols-3 bg-[linear-gradient(180deg,#101112,#0d0e0f)]"
        >
          <span className="sr-only">Exchange metrics: {metricLabel(metrics)}</span>
          {metrics.map((metric, metricIndex) => (
            <span
              key={`${entry.id}-${metric.key}`}
              className={`relative flex min-w-0 items-end px-3 pb-2 pt-[22px] ${
                metricIndex > 0 ? "border-l border-edge" : ""
              }`}
              aria-hidden
            >
              <span className="label absolute left-[5px] top-[5px] block text-[11px] leading-none text-txt-3">
                {metric.label}
              </span>
              <span className="metric-num block truncate text-[14px] leading-none">
                <PanelMetricValue metric={metric} />
              </span>
            </span>
          ))}
        </span>
      </span>
    </button>
  );
}
