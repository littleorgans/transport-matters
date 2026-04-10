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
  return `${(chars / 1024).toFixed(1)}KB`;
}

export function ExchangeList({ exchanges, selectedId, onSelect }: ExchangeListProps) {
  if (exchanges.length === 0) {
    return (
      <div className="flex items-center justify-center p-8 text-zinc-500">
        No exchanges captured yet
      </div>
    );
  }

  return (
    <div className="divide-y divide-zinc-800 overflow-y-auto">
      {exchanges.map((entry) => {
        const isSelected = entry.id === selectedId;
        return (
          <button
            type="button"
            key={entry.id}
            onClick={() => onSelect(entry.id)}
            className={`w-full cursor-pointer px-3 py-2.5 text-left transition-colors ${
              isSelected ? "bg-zinc-800 text-white" : "text-zinc-300 hover:bg-zinc-800/50"
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-sm font-medium">{displayModel(entry.model)}</span>
              <span className="shrink-0 text-xs text-zinc-500">{formatRelativeTime(entry.ts)}</span>
            </div>
            <div className="mt-1 flex items-center gap-3 text-xs text-zinc-500">
              <span>{entry.req.tools_count} tools</span>
              <span>{formatKB(entry.req.total_chars)}</span>
              {entry.res?.stop_reason ? (
                <span
                  className={`rounded px-1.5 py-0.5 text-xs ${
                    entry.res.stop_reason === "end_turn"
                      ? "bg-emerald-900/40 text-emerald-400"
                      : entry.res.stop_reason === "tool_use"
                        ? "bg-blue-900/40 text-blue-400"
                        : "bg-zinc-700 text-zinc-300"
                  }`}
                >
                  {entry.res.stop_reason}
                </span>
              ) : null}
            </div>
          </button>
        );
      })}
    </div>
  );
}
