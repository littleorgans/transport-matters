import { useEffect, useState } from "react";

interface PausedHeaderProps {
  flowId: string;
  pausedAtMs: number;
}

function formatElapsed(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function PausedHeader({ flowId, pausedAtMs }: PausedHeaderProps) {
  const [elapsed, setElapsed] = useState(Date.now() - pausedAtMs);

  useEffect(() => {
    const id = setInterval(() => {
      setElapsed(Date.now() - pausedAtMs);
    }, 1000);
    return () => clearInterval(id);
  }, [pausedAtMs]);

  return (
    <>
      <div className="top-highlight bg-surface px-8 py-3">
        <div className="flex items-center gap-4 min-w-0">
          <div className="flex items-center gap-2.5">
            <span className="h-1.5 w-1.5 rounded-full bg-amber pulse-dot" />
            <span className="label text-amber">Paused</span>
          </div>
          <span className="text-edge-strong">&middot;</span>
          <span className="text-[11px] text-txt-2 metric-num">{flowId.slice(0, 8)}</span>
          <span className="text-edge-strong">&middot;</span>
          <span className="text-[11px] text-amber metric-num">{formatElapsed(elapsed)}</span>
        </div>
      </div>
      <div className="hairline-x" />
    </>
  );
}
