import { useState } from "react";
import { ExchangeDetail } from "./components/ExchangeDetail";
import { ExchangeList } from "./components/ExchangeList";
import { useExchangeStream } from "./hooks/useExchangeStream";

export function App() {
  const { exchanges, connected } = useExchangeStream();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  return (
    <div className="flex h-screen bg-zinc-950 text-zinc-100">
      {/* Left panel */}
      <div className="flex w-1/3 min-w-70 flex-col border-r border-zinc-800">
        <div className="flex items-center justify-between border-b border-zinc-800 px-3 py-2">
          <h1 className="text-sm font-semibold tracking-wide text-zinc-300">Manicure</h1>
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs ${
              connected ? "bg-emerald-900/40 text-emerald-400" : "bg-red-900/40 text-red-400"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-emerald-400" : "bg-red-400"}`}
            />
            {connected ? "Live" : "Disconnected"}
          </span>
        </div>
        <ExchangeList exchanges={exchanges} selectedId={selectedId} onSelect={setSelectedId} />
      </div>

      {/* Right panel */}
      <div className="flex-1 overflow-hidden">
        {selectedId ? (
          <ExchangeDetail id={selectedId} />
        ) : (
          <div className="flex h-full items-center justify-center text-zinc-600">
            Select an exchange to view details
          </div>
        )}
      </div>
    </div>
  );
}
