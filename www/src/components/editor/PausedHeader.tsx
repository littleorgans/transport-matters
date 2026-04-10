import { useEffect, useState } from "react";

interface PausedHeaderProps {
  flowId: string;
  provider: string;
  model: string;
  pausedAtMs: number;
}

function formatElapsed(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function displayModel(provider: string, model: string): string {
  const prefix = `${provider}/`;
  if (model.startsWith(prefix)) {
    return model.slice(prefix.length);
  }
  return model;
}

export function PausedHeader({ flowId, provider, model, pausedAtMs }: PausedHeaderProps) {
  const [elapsed, setElapsed] = useState(Date.now() - pausedAtMs);

  useEffect(() => {
    const id = setInterval(() => {
      setElapsed(Date.now() - pausedAtMs);
    }, 1000);
    return () => clearInterval(id);
  }, [pausedAtMs]);

  return (
    <div className="flex items-center gap-4 border-b border-zinc-800 bg-zinc-900 px-4 py-2">
      <span className="font-mono text-xs text-amber-400">{flowId.slice(0, 8)}</span>
      <span className="text-xs text-zinc-400">
        {provider} / {displayModel(provider, model)}
      </span>
      <span className="font-mono text-xs text-zinc-300">{formatElapsed(elapsed)}</span>
      <span className="ml-auto text-xs text-zinc-600">
        Client timeout: set API_TIMEOUT_MS=3600000 for 1h window
      </span>
    </div>
  );
}
