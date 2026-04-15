import { useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useRef } from "react";
import { contextTokens, displayModel } from "../lib/formatting";
import type { IndexEntry } from "../types";

interface ExchangeListProps {
  exchanges: IndexEntry[];
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

export function ExchangeList({ exchanges, selectedId, onSelect }: ExchangeListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: exchanges.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    // Generous overscan: the list can grow long during a session, and
    // the rows are cheap. Matches JsonView's approach.
    overscan: 30,
    getItemKey: (index) => exchanges[index]?.id ?? index,
  });

  // The selection itself is persisted by uiStore (`partialize`), so it
  // survives tab switches and reloads. What does not survive is the
  // scroll position of the virtualized list — remounting the Intercept
  // panel resets scrollTop to 0, hiding a row that might be hundreds
  // of items down. Scroll the selected row into view once per mount so
  // "coming back to Intercept" lands the user where they left off.
  const scrolledOnMountRef = useRef(false);
  // Fire only when the selection becomes resolvable against the current
  // list; re-running on every list append would hijack the user's
  // scrolling.
  // biome-ignore lint/correctness/useExhaustiveDependencies: intentional deps, see comment above
  useEffect(() => {
    if (scrolledOnMountRef.current || !selectedId || exchanges.length === 0) return;
    const index = exchanges.findIndex((e) => e.id === selectedId);
    if (index < 0) return;
    // rAF so the virtualizer has a rect (ResizeObserver fires on the
    // layout pass that follows mount); without it scrollToIndex sees a
    // 0-height viewport and the computed offset collapses to 0.
    const raf = requestAnimationFrame(() => {
      virtualizer.scrollToIndex(index, { align: "center" });
      scrolledOnMountRef.current = true;
    });
    return () => cancelAnimationFrame(raf);
  }, [selectedId, exchanges.length]);

  if (exchanges.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-12">
        <span className="h-1 w-1 rounded-full bg-txt-3 pulse-dot" />
        <span className="label">Waiting for traffic</span>
      </div>
    );
  }

  return (
    // flex-1 claims the remaining aside height inside its flex-column
    // parent, and min-h-0 overrides flex's default min-height:auto so
    // overflow-y-auto actually engages once rows exceed the viewport.
    <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto">
      <div className="relative w-full" style={{ height: virtualizer.getTotalSize() }}>
        {virtualizer.getVirtualItems().map((vRow) => {
          const entry = exchanges[vRow.index];
          if (!entry) return null;
          const isSelected = entry.id === selectedId;
          const tone = entry.res?.stop_reason ? STOP_TONE[entry.res.stop_reason] : undefined;
          const context = contextTokens(entry.res);
          return (
            <button
              type="button"
              key={vRow.key}
              data-index={vRow.index}
              onClick={() => onSelect(entry.id)}
              className={`group absolute left-0 right-0 top-0 cursor-pointer px-5 py-3.5 text-left transition-colors duration-150 ${
                isSelected ? "row-selected text-txt" : "text-txt-2 hover:bg-surface hover:text-txt"
              }`}
              style={{ transform: `translateY(${vRow.start}px)` }}
            >
              <div className="flex items-center justify-between gap-3">
                <span className="truncate text-[14px] font-medium text-txt">
                  {displayModel(entry.provider, entry.model)}
                </span>
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
              {!isSelected && (
                <span className="absolute bottom-0 left-5 right-5 h-px bg-edge-subtle" />
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
