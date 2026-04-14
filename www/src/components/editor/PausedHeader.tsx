import { useEffect, useState } from "react";
import { displayModel } from "../../lib/formatting";

interface PausedHeaderProps {
  flowId: string;
  pausedAtMs: number;
  provider: string;
  model: string;
}

function formatElapsed(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function PausedHeader({ flowId, pausedAtMs, provider, model }: PausedHeaderProps) {
  const [elapsed, setElapsed] = useState(Date.now() - pausedAtMs);

  useEffect(() => {
    const id = setInterval(() => {
      setElapsed(Date.now() - pausedAtMs);
    }, 1000);
    return () => clearInterval(id);
  }, [pausedAtMs]);

  return (
    <>
      <div className="top-highlight bg-surface">
        <div className="flex items-stretch">
          {/* Status marker — amber wash, caution-lamp feel */}
          <div className="relative flex items-center gap-3 pl-7 pr-6 py-3.5 bg-amber/[0.05] border-r border-edge">
            <span className="absolute left-0 top-0 bottom-0 w-[3px] bg-amber/70" />
            <span className="h-1.5 w-1.5 rounded-full bg-amber pulse-dot" />
            <span className="text-[12px] font-semibold tracking-[0.22em] text-amber uppercase">
              Paused
            </span>
          </div>

          {/* Elapsed — hero readout */}
          <div className="flex flex-col justify-center gap-1 px-6 py-2 border-r border-edge">
            <span className="label">Elapsed</span>
            <span className="text-[17px] text-amber metric-num leading-none tabular-nums">
              {formatElapsed(elapsed)}
            </span>
          </div>

          {/* Provider / model — stretches to fill, letting FLOW anchor
              at the right bookend of the bar */}
          <div className="flex flex-col justify-center gap-1 px-6 py-2 flex-1 min-w-0">
            <span className="label truncate">{provider}</span>
            <span className="text-[13px] text-txt metric-num leading-none truncate">
              {displayModel(provider, model)}
            </span>
          </div>

          {/* Flow id — right-anchored end-cap. Content right-aligned so
              the label and id hug the outer edge, mirroring the PAUSED
              marker on the left as a pair of bookends. */}
          <div className="flex flex-col justify-center items-end gap-1 px-6 py-2">
            <span className="label">Flow</span>
            <span className="text-[13px] text-txt-2 metric-num leading-none whitespace-nowrap">
              {flowId.slice(0, 8)}
            </span>
          </div>
        </div>
      </div>
      <div className="hairline-x" />
    </>
  );
}
