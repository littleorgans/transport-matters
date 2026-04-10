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

const STOP_STYLES: Record<string, string> = {
  end_turn: "text-sage bg-sage/8",
  tool_use: "text-sky bg-sky/8",
};

export function ExchangeList({ exchanges, selectedId, onSelect }: ExchangeListProps) {
  if (exchanges.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 p-12 text-txt-3">
        <span className="text-[12px]">No exchanges captured</span>
        <span className="text-[10px]">Waiting for traffic</span>
      </div>
    );
  }

  return (
    <div className="overflow-y-auto">
      {exchanges.map((entry) => {
        const isSelected = entry.id === selectedId;
        return (
          <button
            type="button"
            key={entry.id}
            onClick={() => onSelect(entry.id)}
            className={`w-full cursor-pointer px-5 py-3.5 text-left transition-all duration-100 border-b border-edge-subtle ${
              isSelected ? "bg-raised text-txt" : "text-txt-2 hover:bg-surface hover:text-txt"
            }`}
          >
            <div className="flex items-center justify-between gap-3">
              <span className="truncate text-[12px] font-medium text-txt">
                {displayModel(entry.model)}
              </span>
              <span className="shrink-0 text-[10px] text-txt-3 tabular-nums">
                {formatRelativeTime(entry.ts)}
              </span>
            </div>
            <div className="mt-2 flex items-center gap-2.5 text-[10px]">
              <span className="tabular-nums">{entry.req.tools_count} tools</span>
              <span className="text-txt-3">|</span>
              <span className="tabular-nums">{formatKB(entry.req.total_chars)}</span>
              {entry.res?.output_tokens != null && (
                <>
                  <span className="text-txt-3">|</span>
                  <span className="tabular-nums text-sky">
                    {entry.res.output_tokens.toLocaleString()} out
                  </span>
                </>
              )}
              {entry.res?.stop_reason && (
                <span
                  className={`ml-auto rounded px-1.5 py-0.5 text-[10px] ${
                    STOP_STYLES[entry.res.stop_reason] ?? "text-txt-2 bg-raised"
                  }`}
                >
                  {entry.res.stop_reason}
                </span>
              )}
            </div>
          </button>
        );
      })}
    </div>
  );
}
