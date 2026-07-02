import { formatCompactChars } from "@tm/core";
import { HoverCard } from "../HoverCard";

export function CompressionBar({
  savedPct,
  before,
  after,
}: {
  savedPct: number;
  before: number;
  after: number;
}) {
  const remaining = Math.max(2, 100 - savedPct);
  return (
    <div className="flex h-2.5 w-full overflow-hidden bg-canvas bar-track">
      <HoverCard
        content={
          <span>
            <span className="text-lavender">sent</span> {formatCompactChars(after)} ({remaining}%)
          </span>
        }
      >
        <div
          className="h-full bg-gradient-to-r from-lavender/60 to-lavender/30 transition-all"
          style={{ width: `${remaining}%` }}
        />
      </HoverCard>
      {savedPct > 0 && (
        <HoverCard
          content={
            <span>
              <span className="text-sage">saved</span> {formatCompactChars(before - after)} (
              {savedPct}%)
            </span>
          }
        >
          <div className="h-full flex-1" />
        </HoverCard>
      )}
    </div>
  );
}
