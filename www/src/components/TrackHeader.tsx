import type { CSSProperties } from "react";
import { agentRailStyle } from "../lib/agentPalette";
import type { ExchangeTrack } from "../types";
import type { OrphanAnchorMeta } from "./exchangeListRows";

type TrackDepthStyle = CSSProperties & {
  "--track-depth": string;
  "--agent-rail": string;
  "--agent-rail-rgb": string;
};

interface TrackHeaderProps {
  track: ExchangeTrack;
  depth: number;
  index: number;
  offsetTop: number;
  anchorMeta?: OrphanAnchorMeta;
  isCollapsed: boolean;
  onToggle: (trackId: string) => void;
  onFocusParent?: (trackId: string) => void;
}

function turnLabel(count: number): string {
  return `${count.toLocaleString()} ${count === 1 ? "turn" : "turns"}`;
}

function trackLabel(track: ExchangeTrack): string {
  return track.track_role === "subagent" ? "subagent" : "root";
}

function trackDisplayName(track: ExchangeTrack): string {
  return (
    track.track_display_name ??
    track.exchanges.find((entry) => entry.track_display_name)?.track_display_name ??
    "Subagent"
  );
}

export function TrackHeader({
  track,
  depth,
  index,
  offsetTop,
  anchorMeta,
  isCollapsed,
  onToggle,
  onFocusParent,
}: TrackHeaderProps) {
  const label = trackLabel(track);
  const displayName = trackDisplayName(track);
  const turnCount = track.exchanges.length;
  const toggleLabel = `${isCollapsed ? "Expand" : "Collapse"} track ${track.track_id}`;
  const style: TrackDepthStyle = {
    transform: `translateY(${offsetTop}px)`,
    "--track-depth": String(depth),
    ...agentRailStyle(track.track_id),
  };
  const statusTone =
    track.status === "live"
      ? "text-sage"
      : track.status === "pending"
        ? "text-amber"
        : "text-txt-3";

  return (
    <div
      data-index={index}
      data-testid={`track-header-${track.track_id}`}
      data-depth={depth}
      className={`absolute left-0 right-0 top-0 min-h-[92px] bg-canvas py-0 ${
        track.status === "closed" ? "opacity-65" : ""
      }`}
      style={style}
    >
      <div className="relative min-h-[92px]">
        <div
          className="grid min-h-[92px] min-w-0 grid-cols-[8px_52px_minmax(0,1fr)] overflow-hidden border border-sky/25 bg-[linear-gradient(180deg,rgb(var(--sky-rgb)/0.08),rgb(var(--sky-rgb)/0.025))] shadow-[inset_0_1px_0_0_rgb(var(--highlight-rgb)/0.05),inset_0_-1px_0_0_rgb(var(--shadow-rgb)/0.35)]"
          title={`Track ${track.track_id}`}
        >
          <span
            className="bg-[var(--agent-rail)] shadow-[0_0_22px_rgb(var(--agent-rail-rgb)/0.32)]"
            aria-hidden
          />
          <button
            type="button"
            aria-label={toggleLabel}
            aria-expanded={!isCollapsed}
            onClick={() => onToggle(track.track_id)}
            className="group/toggle relative flex cursor-pointer items-center justify-center border-r border-[rgb(var(--agent-rail-rgb)/0.25)] bg-canvas/75 text-[16px] text-[var(--agent-rail)] transition-colors hover:bg-raised hover:text-txt focus-visible:border-accent focus-visible:outline-none"
          >
            <span
              className="flex h-[60px] w-[38px] items-center justify-center border border-edge-strong bg-[linear-gradient(180deg,#101112,#080909)] text-[var(--agent-rail)] group-hover/toggle:border-[rgb(var(--agent-rail-rgb)/0.45)]"
              aria-hidden
            >
              {isCollapsed ? "›" : "⌄"}
            </span>
          </button>
          <button
            type="button"
            onClick={() => onFocusParent?.(track.track_id)}
            className="min-w-0 flex-1 cursor-pointer px-4 py-3 text-left transition-colors hover:bg-raised/35 focus-visible:outline-none"
          >
            <span className="flex h-full min-w-0 items-center justify-between gap-3">
              <span className="min-w-0">
                <span className="label mb-2 block text-[12px] text-[var(--agent-rail)]">
                  {label}
                </span>
                <span className="block truncate text-[20px] font-semibold leading-none text-txt">
                  {displayName}
                </span>
              </span>
              <span className="flex shrink-0 items-baseline gap-2 border border-[rgb(var(--agent-rail-rgb)/0.25)] bg-canvas/35 px-3 py-2">
                {anchorMeta?.orphanAnchor && (
                  <>
                    <span
                      className="label text-[10px] text-amber"
                      title={`Spawn anchor ${anchorMeta.missingAnchorId} is outside the fetched exchange window`}
                    >
                      anchor outside view
                    </span>
                    <span className="text-txt-3" aria-hidden>
                      ·
                    </span>
                  </>
                )}
                <span className={`label text-[11px] ${statusTone}`}>{track.status}</span>
                <span className="text-txt-3" aria-hidden>
                  ·
                </span>
                <span className="metric-num text-[11px] leading-none text-txt-3">
                  {turnLabel(turnCount)}
                </span>
              </span>
            </span>
          </button>
        </div>
      </div>
    </div>
  );
}
