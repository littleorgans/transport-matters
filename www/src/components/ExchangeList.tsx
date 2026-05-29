import { useVirtualizer } from "@tanstack/react-virtual";
import { useMemo, useRef, useState } from "react";
import type { ExchangeTrack, IndexEntry } from "../types";
import { ExchangeTurnCard } from "./ExchangeTurnCard";
import { projectAnchoredRows } from "./exchangeListRows";
import { Toggle } from "./Toggle";
import { TrackHeader } from "./TrackHeader";

interface ExchangeListProps {
  exchanges: IndexEntry[];
  trackTree: ExchangeTrack[];
  currentRunId: string | null;
  includeHistory: boolean;
  onIncludeHistoryChange: (next: boolean) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
  collapsedTrackIds?: readonly string[];
  onToggleCollapsedTrack?: (trackId: string) => void;
}

// Fixed virtual rows keep long sessions cheap. Root and subagent turns
// share the same instrument panel layout.
const TRACK_ROW_HEIGHT = 92;
const EXCHANGE_ROW_HEIGHT = 250;
const EMPTY_TRACK_IDS: string[] = [];
const IGNORE_COLLAPSED_TRACK_TOGGLE = () => {};

function findTrack(tracks: ExchangeTrack[], trackId: string): ExchangeTrack | null {
  for (const track of tracks) {
    if (track.track_id === trackId) return track;
    const child = findTrack(track.children, trackId);
    if (child) return child;
  }
  return null;
}

function focusEntryForTrack(tracks: ExchangeTrack[], trackId: string): IndexEntry | null {
  const track = findTrack(tracks, trackId);
  if (!track) return null;
  if (track.parent_track_id) {
    const parent = findTrack(tracks, track.parent_track_id);
    const anchorId = track.track_spawn_exchange_id;
    const anchored = anchorId ? parent?.exchanges.find((entry) => entry.id === anchorId) : null;
    if (anchored) return anchored;
    // Legacy fallback: locate the most recent parent exchange at or before the
    // child's first (oldest) exchange. Track exchanges are sorted newest-first,
    // so .at(-1) reads the oldest and .find returns the latest match.
    const firstChild = track.exchanges.at(-1);
    const firstChildTs = firstChild ? new Date(firstChild.ts).getTime() : null;
    const parentExchange =
      firstChildTs == null
        ? parent?.exchanges[0]
        : parent?.exchanges.find((entry) => new Date(entry.ts).getTime() <= firstChildTs);
    if (parentExchange) return parentExchange;
  }
  return track.exchanges.at(-1) ?? null;
}

export function exchangeListSessionKey(
  currentRunId: string | null,
  exchanges: IndexEntry[],
): string {
  return currentRunId ?? exchanges[0]?.run_id ?? "history";
}

interface ExchangeListHeaderProps {
  count: number;
  historyCount: number;
  includeHistory: boolean;
  onIncludeHistoryChange: (next: boolean) => void;
  previewWaiting: boolean;
  onPreviewWaitingChange: (next: boolean) => void;
}

function ExchangeListHeader({
  count,
  historyCount,
  includeHistory,
  onIncludeHistoryChange,
  previewWaiting,
  onPreviewWaitingChange,
}: ExchangeListHeaderProps) {
  return (
    <div className="border-b border-edge px-5 py-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="label">Intercept</span>
            <span className="metric-num text-[12px] text-txt-2">{count}</span>
            {includeHistory && historyCount > 0 && (
              <span className="label text-sky">{historyCount} prior</span>
            )}
          </div>
          <p className="mt-2 text-[12px] leading-5 text-txt-3">
            {includeHistory
              ? "Showing prior runs alongside live traffic for this workspace."
              : "Live session only. Turn on history to inspect prior runs."}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2 text-[11px] uppercase tracking-[0.18em] text-txt-3">
          <div className="flex items-center gap-2">
            <Toggle
              checked={previewWaiting}
              onChange={onPreviewWaitingChange}
              label="Preview open waiting cards"
              size="sm"
            />
            <span>Waiting</span>
          </div>
          <div className="flex items-center gap-2">
            <Toggle
              checked={includeHistory}
              onChange={onIncludeHistoryChange}
              label="Show prior runs"
              size="sm"
            />
            <span>History</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function ExchangeListEmptyState({ includeHistory }: { includeHistory: boolean }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 p-12 text-center">
      <span className="h-1 w-1 rounded-full bg-txt-3 pulse-dot" />
      <span className="label">
        {includeHistory ? "No captured history in this workspace" : "Waiting for traffic"}
      </span>
    </div>
  );
}

export function ExchangeList({
  exchanges,
  trackTree,
  currentRunId,
  includeHistory,
  onIncludeHistoryChange,
  selectedId,
  onSelect,
  collapsedTrackIds = EMPTY_TRACK_IDS,
  onToggleCollapsedTrack = IGNORE_COLLAPSED_TRACK_TOGGLE,
}: ExchangeListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [previewWaiting, setPreviewWaiting] = useState(false);
  const historyCount = currentRunId
    ? exchanges.filter((entry) => entry.run_id !== currentRunId).length
    : 0;
  const collapsedTrackSet = useMemo(() => new Set(collapsedTrackIds), [collapsedTrackIds]);
  const rows = useMemo(
    () => projectAnchoredRows(trackTree, collapsedTrackSet),
    [trackTree, collapsedTrackSet],
  );

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (index) =>
      rows[index]?.type === "track" ? TRACK_ROW_HEIGHT : EXCHANGE_ROW_HEIGHT,
    // Generous overscan: the list can grow long during a session, and
    // the rows are cheap. Matches JsonView's approach.
    overscan: 30,
    getItemKey: (index) => rows[index]?.key ?? index,
  });
  const focusTrack = (trackId: string) => {
    const entry = focusEntryForTrack(trackTree, trackId);
    if (entry) onSelect(entry.id);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ExchangeListHeader
        count={exchanges.length}
        historyCount={historyCount}
        includeHistory={includeHistory}
        onIncludeHistoryChange={onIncludeHistoryChange}
        previewWaiting={previewWaiting}
        onPreviewWaitingChange={setPreviewWaiting}
      />

      {rows.length === 0 ? (
        <ExchangeListEmptyState includeHistory={includeHistory} />
      ) : (
        // flex-1 claims the remaining aside height inside its flex-column
        // parent, and min-h-0 overrides flex's default min-height:auto so
        // overflow-y-auto actually engages once rows exceed the viewport.
        <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto">
          <div className="relative w-full" style={{ height: virtualizer.getTotalSize() }}>
            {virtualizer.getVirtualItems().map((vRow) => {
              const row = rows[vRow.index];
              if (!row) return null;
              if (row.type === "track") {
                const isCollapsed = collapsedTrackSet.has(row.track.track_id);
                return (
                  <TrackHeader
                    key={vRow.key}
                    track={row.track}
                    depth={row.depth}
                    index={vRow.index}
                    offsetTop={vRow.start}
                    anchorMeta={row.meta}
                    isCollapsed={isCollapsed}
                    onToggle={onToggleCollapsedTrack}
                    onFocusParent={focusTrack}
                  />
                );
              }
              const { entry } = row;
              return (
                <ExchangeTurnCard
                  key={vRow.key}
                  entry={entry}
                  depth={row.depth}
                  isHistorical={
                    includeHistory && currentRunId != null && entry.run_id !== currentRunId
                  }
                  isSelected={entry.id === selectedId}
                  previewWaiting={previewWaiting}
                  index={vRow.index}
                  offsetTop={vRow.start}
                  turnSequence={row.turnSequence}
                  onSelect={onSelect}
                />
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
