import { useEffect, useState } from "react";

interface PausedHeaderProps {
  flowId: string;
  provider: string;
  model: string;
  pausedAtMs: number;
  children?: React.ReactNode;
}

function formatElapsed(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function displayModel(provider: string, model: string): string {
  const prefix = `${provider}/`;
  return model.startsWith(prefix) ? model.slice(prefix.length) : model;
}

export function PausedHeader({ flowId, provider, model, pausedAtMs, children }: PausedHeaderProps) {
  const [elapsed, setElapsed] = useState(Date.now() - pausedAtMs);

  useEffect(() => {
    const id = setInterval(() => {
      setElapsed(Date.now() - pausedAtMs);
    }, 1000);
    return () => clearInterval(id);
  }, [pausedAtMs]);

  return (
    <div className="border-b border-edge bg-surface px-6 py-4">
      <div className="flex items-center justify-between gap-4">
        {/* Left: flow info */}
        <div className="flex items-center gap-4 min-w-0">
          <span className="text-[11px] text-amber tabular-nums">{flowId.slice(0, 8)}</span>
          <span className="text-[11px] text-txt-2">
            {provider} / {displayModel(provider, model)}
          </span>
          <span className="flex items-center gap-1.5 text-[11px] text-txt tabular-nums">
            <span className="h-1.5 w-1.5 rounded-full bg-amber pulse-dot" />
            {formatElapsed(elapsed)}
          </span>
        </div>

        {/* Right: action buttons (passed as children) */}
        {children}
      </div>
    </div>
  );
}
