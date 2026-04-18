import { useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useRef } from "react";
import { contextTokens, displayModel } from "../lib/formatting";
import type { IndexEntry } from "../types";
import { Toggle } from "./Toggle";

interface ExchangeListProps {
  exchanges: IndexEntry[];
  currentRunId: string | null;
  includeHistory: boolean;
  onIncludeHistoryChange: (next: boolean) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

// Two-line row (title + metrics) with py-3.5 padding and an mt-2 gap.
// Title uses ``truncate`` and the metrics line never wraps, so rows
// are uniform and we can skip ``measureElement``.
const ROW_HEIGHT = 76;

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

const STOP_TONE: Record<string, string> = {
  end_turn: "text-sage",
  tool_use: "text-sky",
  max_tokens: "text-amber",
};

interface ExchangeListHeaderProps {
  count: number;
  historyCount: number;
  includeHistory: boolean;
  onIncludeHistoryChange: (next: boolean) => void;
}

function ExchangeListHeader({
  count,
  historyCount,
  includeHistory,
  onIncludeHistoryChange,
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
        <div className="flex shrink-0 items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-txt-3">
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

interface ExchangeRowProps {
  entry: IndexEntry;
  isHistorical: boolean;
  isSelected: boolean;
  index: number;
  offsetTop: number;
  onSelect: (id: string) => void;
}

function ExchangeRow({
  entry,
  isHistorical,
  isSelected,
  index,
  offsetTop,
  onSelect,
}: ExchangeRowProps) {
  const tone = entry.res?.stop_reason ? STOP_TONE[entry.res.stop_reason] : undefined;
  const context = contextTokens(entry.res);

  return (
    <button
      type="button"
      data-index={index}
      onClick={() => onSelect(entry.id)}
      className={`group absolute left-0 right-0 top-0 cursor-pointer px-5 py-3.5 text-left transition-colors duration-150 ${
        isSelected ? "row-selected text-txt" : "text-txt-2 hover:bg-surface hover:text-txt"
      }`}
      style={{ transform: `translateY(${offsetTop}px)` }}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate text-[14px] font-medium text-txt">
            {displayModel(entry.provider, entry.model)}
          </span>
          {isHistorical && (
            <span
              className={`label shrink-0 ${isSelected ? "text-sky" : "text-txt-3"}`}
              title={entry.run_id ? `run ${entry.run_id}` : "Captured before this run"}
            >
              prior run
            </span>
          )}
        </div>
        <span
          className={`shrink-0 text-[11px] metric-num uppercase tracking-wider ${
            isSelected ? "text-accent/80" : "text-txt-3"
          }`}
        >
          {formatRelativeTime(entry.ts)}
        </span>
      </div>
      <div
        className={`mt-2 flex items-center gap-2.5 text-[12px] ${
          isSelected ? "text-txt-2" : "text-txt-3"
        }`}
      >
        <span className="metric-num">{entry.req.tools_count} tools</span>
        {context > 0 && (
          <>
            <span className="text-edge-strong">&middot;</span>
            <span className="metric-num text-sky">{context.toLocaleString()} tokens</span>
          </>
        )}
        {entry.res?.stop_reason && (
          <span
            className={`ml-auto label ${tone ?? "text-txt-3"}`}
            title={`stop: ${entry.res.stop_reason}`}
          >
            {entry.res.stop_reason}
          </span>
        )}
      </div>
      {!isSelected && <span className="absolute bottom-0 left-5 right-5 h-px bg-edge-subtle" />}
    </button>
  );
}

export function ExchangeList({
  exchanges,
  currentRunId,
  includeHistory,
  onIncludeHistoryChange,
  selectedId,
  onSelect,
}: ExchangeListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const historyCount = currentRunId
    ? exchanges.filter((entry) => entry.run_id !== currentRunId).length
    : 0;

  const virtualizer = useVirtualizer({
    count: exchanges.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    // Generous overscan: the list can grow long during a session, and
    // the rows are cheap. Matches JsonView's approach.
    overscan: 30,
    getItemKey: (index) => exchanges[index]?.id ?? index,
  });
  const selectedIndex = selectedId ? exchanges.findIndex((entry) => entry.id === selectedId) : -1;

  // The selection itself is persisted by uiStore (`partialize`), so it
  // survives tab switches and reloads. What does not survive is the
  // scroll position of the virtualized list — remounting the Intercept
  // panel resets scrollTop to 0, and toggling history can temporarily
  // hide then re-show the selected row. Track the last row we
  // intentionally scrolled to so restored selections recentre once
  // without hijacking normal browsing on every list append.
  const lastScrolledSelectionRef = useRef<string | null>(null);
  // biome-ignore lint/correctness/useExhaustiveDependencies: keyed to selection visibility, not every list mutation
  useEffect(() => {
    if (!selectedId || exchanges.length === 0) {
      lastScrolledSelectionRef.current = null;
      return;
    }
    if (selectedIndex < 0) {
      lastScrolledSelectionRef.current = null;
      return;
    }
    if (lastScrolledSelectionRef.current === selectedId) return;
    // rAF so the virtualizer has a rect (ResizeObserver fires on the
    // layout pass that follows mount); without it scrollToIndex sees a
    // 0-height viewport and the computed offset collapses to 0.
    const raf = requestAnimationFrame(() => {
      virtualizer.scrollToIndex(selectedIndex, { align: "center" });
      lastScrolledSelectionRef.current = selectedId;
    });
    return () => cancelAnimationFrame(raf);
  }, [selectedId, selectedIndex]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ExchangeListHeader
        count={exchanges.length}
        historyCount={historyCount}
        includeHistory={includeHistory}
        onIncludeHistoryChange={onIncludeHistoryChange}
      />

      {exchanges.length === 0 ? (
        <ExchangeListEmptyState includeHistory={includeHistory} />
      ) : (
        // flex-1 claims the remaining aside height inside its flex-column
        // parent, and min-h-0 overrides flex's default min-height:auto so
        // overflow-y-auto actually engages once rows exceed the viewport.
        <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto">
          <div className="relative w-full" style={{ height: virtualizer.getTotalSize() }}>
            {virtualizer.getVirtualItems().map((vRow) => {
              const entry = exchanges[vRow.index];
              if (!entry) return null;
              return (
                <ExchangeRow
                  key={vRow.key}
                  entry={entry}
                  isHistorical={
                    includeHistory && currentRunId != null && entry.run_id !== currentRunId
                  }
                  isSelected={entry.id === selectedId}
                  index={vRow.index}
                  offsetTop={vRow.start}
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
