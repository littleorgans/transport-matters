import { contextTokens, displayModel } from "../lib/formatting";
import type { IndexEntry } from "../types";

interface ExchangeListProps {
  exchanges: IndexEntry[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

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
    <div className="flex-1 min-h-0 overflow-y-auto">
      {exchanges.map((entry) => {
        const isSelected = entry.id === selectedId;
        const tone = entry.res?.stop_reason ? STOP_TONE[entry.res.stop_reason] : undefined;
        const context = contextTokens(entry.res);
        return (
          <button
            type="button"
            key={entry.id}
            onClick={() => onSelect(entry.id)}
            className={`group relative w-full cursor-pointer px-5 py-3.5 text-left transition-colors duration-150 ${
              isSelected ? "row-selected text-txt" : "text-txt-2 hover:bg-surface hover:text-txt"
            }`}
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
  );
}
