import type { CSSProperties } from "react";
import { agentRailStyle } from "../lib/agentPalette";
import { contextTokens, displayModel } from "../lib/formatting";
import type { CodexTurnListSummary, IndexEntry } from "../types";

type DepthStyle = CSSProperties & {
  "--track-depth": string;
  "--agent-rail": string;
  "--agent-rail-rgb": string;
};

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
  unit?: string;
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

function pluralUnit(count: number, singular: string, plural = `${singular}s`): string {
  return count === 1 ? singular : plural;
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
        <span key={key} className={digit === "0" ? "text-txt-3" : "text-txt"}>
          {digit ?? ""}
        </span>
      ))}
    </>
  );
}

function statusDisplay(
  entry: IndexEntry,
  previewWaiting: boolean,
): {
  label: string;
  tone: string;
  marker: "check" | "square" | "none";
} | null {
  if (previewWaiting) return { label: "WAITING", tone: "amber", marker: "square" };
  const turnStatus = entry.codex_turn?.status;
  const stopReason = entry.res?.stop_reason;
  if (turnStatus === "open") return { label: "WAITING", tone: "amber", marker: "square" };
  if (turnStatus === "completed") return { label: "COMPLETE", tone: "sage", marker: "check" };
  if (turnStatus === "failed") return { label: "FAILED", tone: "rose", marker: "square" };
  if (turnStatus === "interrupted") return { label: "STOPPED", tone: "lavender", marker: "square" };
  if (stopReason) return { label: stopReason.toUpperCase(), tone: "txt", marker: "none" };
  return null;
}

function transportTitle(turn?: CodexTurnListSummary | null): string | undefined {
  if (!turn) return undefined;
  const parts = [
    `turn ${turn.turn_index}`,
    `frames ${turn.message_range_start}->${turn.message_range_end}`,
    turn.terminal_cause?.replaceAll("_", " "),
    turn.stop_reason,
  ].filter(Boolean);
  if (turn.status === "open") parts.push("waiting for Codex transport");
  return parts.join(" | ");
}

function previewTransportTitle(turn?: CodexTurnListSummary | null): string {
  const turnLabel = turn ? `turn ${turn.turn_index}` : "request";
  return `${turnLabel} | previewing open waiting transport`;
}

function panelMetrics(entry: IndexEntry): PanelMetric[] {
  const turn = entry.codex_turn;
  const tools = turn?.tool_calls ?? entry.res?.tool_calls ?? entry.req.tools_count;
  const text = turn?.text_chars ?? entry.res?.text_chars ?? entry.req.total_chars;
  const thirdMetric =
    turn != null || entry.provider === "codex"
      ? {
          key: "frames",
          label: "Frames",
          value: turn != null ? `${turn.message_range_start}->${turn.message_range_end}` : "...",
        }
      : {
          key: "messages",
          label: "Msgs",
          value: formatCount(entry.req.messages_count),
        };

  return [
    {
      key: "tools",
      label: "Tools",
      value: formatCount(tools),
    },
    {
      key: "text",
      label: "Text",
      value: formatCount(text),
      unit: pluralUnit(text, "char"),
    },
    thirdMetric,
  ];
}

function tokenValue(entry: IndexEntry): number {
  const context = contextTokens(entry.res);
  if (context > 0) return context;
  return entry.res?.input_tokens ?? 0;
}

function metricLabel(metrics: PanelMetric[]): string {
  return metrics
    .map((metric) => `${metric.label}: ${metric.value}${metric.unit ? ` ${metric.unit}` : ""}`)
    .join(", ");
}

function statusClasses(tone: string): string {
  if (tone === "amber") return "border-amber/35 text-amber";
  if (tone === "sage") return "border-sage/35 text-sage";
  if (tone === "rose") return "border-rose/35 text-rose";
  if (tone === "lavender") return "border-lavender/35 text-lavender";
  return "border-edge text-txt-2";
}

function markerClasses(tone: string): string {
  if (tone === "amber") return "border-amber bg-amber shadow-[0_0_18px_rgb(var(--amber-rgb)/0.35)]";
  if (tone === "sage") return "border-sage text-sage shadow-[0_0_18px_rgb(var(--sage-rgb)/0.28)]";
  if (tone === "rose") return "border-rose bg-rose/75";
  if (tone === "lavender") return "border-lavender bg-lavender/75";
  return "border-edge";
}

function PanelMetricValue({ metric }: { metric: PanelMetric }) {
  if (metric.key === "frames") {
    const [start, end] = metric.value.split("->");
    if (end == null) {
      return <span className="text-txt-3">{metric.value}</span>;
    }
    return (
      <span className="inline-flex items-baseline gap-1.5">
        <span className={start === "0" ? "text-txt-3" : "text-txt"}>{start}</span>
        <span className="text-txt-2">→</span>
        <span className={end === "0" ? "text-txt-3" : "text-txt"}>{end}</span>
      </span>
    );
  }

  const isZero = metric.value === "0";
  return (
    <span className="inline-flex items-baseline gap-2">
      <span className={isZero ? "text-txt-3" : "text-txt"}>{metric.value}</span>
      {metric.unit && <span className="text-[12px] leading-none text-txt-3">{metric.unit}</span>}
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
  const isOpen = previewWaiting || entry.codex_turn?.status === "open";
  const isSubagent = depth > 0;
  const status = statusDisplay(entry, previewWaiting);
  const metrics = panelMetrics(entry);
  const tokens = tokenValue(entry);
  const style: DepthStyle = {
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
      className={`group absolute left-0 right-0 top-0 min-h-[212px] cursor-pointer text-left text-txt-2 ${
        isSubagent ? "grid grid-cols-[1px_8px_52px_minmax(0,1fr)] py-0" : "py-2"
      }`}
      style={style}
    >
      {isSubagent && <span aria-hidden />}
      {isSubagent && (
        <span
          className="min-h-[212px] bg-[var(--agent-rail)] shadow-[0_0_22px_rgb(var(--agent-rail-rgb)/0.32)]"
          aria-hidden
        />
      )}
      {isSubagent && (
        <span
          aria-hidden
          className="flex min-h-[212px] items-start justify-center border-y border-r border-[rgb(var(--agent-rail-rgb)/0.25)] bg-[linear-gradient(180deg,#101112,#080909)] pt-[76px] shadow-[inset_0_1px_0_rgb(var(--highlight-rgb)/0.05)]"
        >
          <span className="label text-[11px] text-[var(--agent-rail)]">Sub</span>
        </span>
      )}
      <span
        className={`relative grid min-h-[196px] min-w-0 grid-rows-[58px_86px_52px] overflow-hidden border bg-[linear-gradient(180deg,#101112,#070707)] shadow-[inset_0_1px_0_rgb(var(--highlight-rgb)/0.07),inset_0_-22px_45px_rgb(var(--shadow-rgb)/0.35)] transition-colors duration-150 ${
          isSelected
            ? "border-accent row-selected"
            : isOpen
              ? "border-amber/45 group-hover:border-amber/65"
              : "border-edge-strong group-hover:border-edge"
        } ${isSubagent ? "min-h-[212px]" : ""}`}
      >
        {isOpen && (
          <span className="absolute inset-x-0 top-0 h-px overflow-hidden bg-amber/20">
            <span className="transport-scan block h-full w-1/3 bg-amber/85" />
          </span>
        )}

        <span className="flex min-w-0 items-center justify-between gap-4 border-b border-edge px-4">
          <span className="flex min-w-0 items-center gap-3">
            <span className="truncate text-[17px] font-semibold leading-none text-txt">
              {displayModel(entry.provider, entry.model)}
            </span>
            {isHistorical && (
              <span
                className="chip px-2 py-1 text-[9px] text-sky"
                title={entry.run_id ? `run ${entry.run_id}` : "Captured before this run"}
              >
                prior
              </span>
            )}
          </span>
          <span className="metric-num shrink-0 border border-edge-strong bg-canvas/35 px-3 py-1.5 text-[12px] uppercase text-txt-2">
            {formatRelativeTime(entry.ts)}
          </span>
        </span>

        <span className="flex min-w-0 items-center justify-start gap-4 border-b border-edge px-4 py-3">
          <span className="grid h-[60px] w-fit max-w-full grid-cols-[78px_138px_134px] border border-edge-strong bg-canvas/30">
            <span className="relative min-w-0 border-r border-edge px-3 pb-2 pt-7">
              <span className="label absolute left-[5px] top-[5px] text-[12px] text-txt-3">
                Turn
              </span>
              <span className="metric-num flex h-full items-center justify-center text-[17px] leading-none text-txt-3">
                <TurnValue turn={entry.codex_turn} fallbackIndex={turnSequence} />
              </span>
            </span>

            <span className="relative min-w-0 border-r border-edge px-3 pb-2 pt-7">
              <span className="label absolute left-[5px] top-[5px] text-[12px] text-txt-3">
                Tokens
              </span>
              {isOpen ? (
                <span className="flex h-full min-w-0 items-center">
                  <span className="grid grid-cols-[repeat(10,minmax(0,1fr))] gap-1" aria-hidden>
                    {TOKEN_SEGMENTS.map((segment) => (
                      <span
                        key={`${entry.id}-${segment.key}`}
                        className="token-segment h-3 border border-edge-strong bg-surface"
                        style={{ animationDelay: segment.delay }}
                      />
                    ))}
                  </span>
                </span>
              ) : (
                <span
                  data-testid={`exchange-primary-metric-${entry.id}`}
                  className="metric-num flex h-full items-center justify-center truncate text-[17px] leading-none text-sky"
                >
                  {formatCount(tokens)}
                </span>
              )}
            </span>

            <span
              data-testid={`exchange-status-${entry.id}`}
              title={
                previewWaiting
                  ? previewTransportTitle(entry.codex_turn)
                  : transportTitle(entry.codex_turn)
              }
              className={`relative flex min-w-0 flex-col items-start justify-center gap-2 px-3 pb-2 pt-7 ${status ? statusClasses(status.tone) : "text-txt-3"}`}
            >
              <span className="label absolute left-[5px] top-[5px] text-[12px] text-txt-3">
                State
              </span>
              <span className="flex min-w-0 items-center justify-start gap-2">
                {status?.marker === "check" && (
                  <span
                    className={`flex h-4 w-4 items-center justify-center border text-[12px] leading-none ${markerClasses(status.tone)}`}
                    aria-hidden
                  >
                    ✓
                  </span>
                )}
                {status?.marker === "square" && (
                  <span className={`h-3 w-3 border ${markerClasses(status.tone)}`} aria-hidden />
                )}
                <span className="label truncate text-[14px]">{status?.label ?? "PENDING"}</span>
              </span>
            </span>
          </span>
          <span
            aria-hidden
            className="h-px min-w-10 flex-1 bg-gradient-to-r from-edge via-edge/55 to-transparent"
          />
        </span>

        <span
          data-testid={`exchange-metrics-${entry.id}`}
          className="grid min-w-0 grid-cols-3 bg-[linear-gradient(180deg,#101112,#0d0e0f)]"
        >
          <span className="sr-only">Exchange metrics: {metricLabel(metrics)}</span>
          {metrics.map((metric, metricIndex) => (
            <span
              key={`${entry.id}-${metric.key}`}
              className={`flex min-w-0 flex-col justify-center px-4 py-1.5 ${
                metricIndex > 0 ? "border-l border-edge" : ""
              }`}
              aria-hidden
            >
              <span className="label mb-1 block text-[11px] leading-none text-txt-3">
                {metric.label}
              </span>
              <span
                className={`metric-num block truncate leading-none ${
                  metric.key === "frames" ? "text-[18px]" : "text-[22px]"
                }`}
              >
                <PanelMetricValue metric={metric} />
              </span>
            </span>
          ))}
        </span>
      </span>
    </button>
  );
}
