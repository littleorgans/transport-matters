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

function displayModel(model: string): string {
  return model.replace(/^anthropic\//, "");
}

function formatKB(chars: number): string {
  return `${(chars / 1024).toFixed(1)}K`;
}

const STOP_TONE: Record<string, string> = {
  end_turn: "text-sage",
  tool_use: "text-sky",
  max_tokens: "text-amber",
};

export function ExchangeList({ exchanges, selectedId, onSelect }: ExchangeListProps) {
  if (exchanges.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 p-12">
        <span className="h-1 w-1 rounded-full bg-txt-3 pulse-dot" />
        <span className="label">Waiting for traffic</span>
      </div>
    );
  }

  return (
    <div className="overflow-y-auto">
      {exchanges.map((entry) => {
        const isSelected = entry.id === selectedId;
        const tone = entry.res?.stop_reason ? STOP_TONE[entry.res.stop_reason] : undefined;
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
              <span className="truncate text-[12px] font-medium text-txt">
                {displayModel(entry.model)}
              </span>
              <span
                className={`shrink-0 text-[9px] metric-num uppercase tracking-wider ${
                  isSelected ? "text-sky/80" : "text-txt-3"
                }`}
              >
                {formatRelativeTime(entry.ts)}
              </span>
            </div>
            <div
              className={`mt-2 flex items-center gap-2.5 text-[10px] ${
                isSelected ? "text-txt-2" : "text-txt-3"
              }`}
            >
              <span className="metric-num">{entry.req.tools_count} tools</span>
              <span className="text-edge-strong">&middot;</span>
              <span className="metric-num">{formatKB(entry.req.total_chars)}</span>
              {entry.res?.output_tokens != null && (
                <>
                  <span className="text-edge-strong">&middot;</span>
                  <span className="metric-num text-sky">
                    {entry.res.output_tokens.toLocaleString()} out
                  </span>
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
