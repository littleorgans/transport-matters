import { contextTokens, formatCompactChars } from "../../lib/formatting";
import type { UsageStats } from "../../types";
import { HoverCard } from "../HoverCard";

// output_tokens is intentionally absent from this bar: it measures
// generation, not context occupancy, so it renders in the meta row
// beside `messages`. See contextTokens() for the formula rationale.
export function TokenBar({ usage }: { usage: UsageStats }) {
  const {
    input_tokens: input,
    cache_creation_input_tokens: cacheCreation,
    cache_read_input_tokens: cacheRead,
  } = usage;
  const context = contextTokens(usage);
  if (context === 0) return null;

  const denom = context;
  const cacheReadPct = (cacheRead / denom) * 100;
  const cacheCreationPct = (cacheCreation / denom) * 100;
  const inputPct = (input / denom) * 100;

  return (
    <div className="space-y-4">
      <div className="flex h-2.5 w-full overflow-hidden bg-canvas bar-track">
        {cacheRead > 0 && (
          <HoverCard
            content={
              <span>
                <span className="text-teal">cache read</span> {cacheRead.toLocaleString()} tokens (
                {cacheReadPct.toFixed(1)}%)
              </span>
            }
          >
            <div className="h-full bg-teal/70" style={{ width: `${cacheReadPct}%` }} />
          </HoverCard>
        )}
        {cacheCreation > 0 && (
          <HoverCard
            content={
              <span>
                <span className="text-lavender">cache write</span> {cacheCreation.toLocaleString()}{" "}
                tokens ({cacheCreationPct.toFixed(1)}%)
              </span>
            }
          >
            <div className="h-full bg-lavender/70" style={{ width: `${cacheCreationPct}%` }} />
          </HoverCard>
        )}
        {input > 0 && (
          <HoverCard
            content={
              <span>
                <span className="text-txt">input</span> {input.toLocaleString()} tokens (
                {inputPct.toFixed(1)}%)
              </span>
            }
          >
            <div className="h-full bg-txt-3/60" style={{ width: `${inputPct}%` }} />
          </HoverCard>
        )}
      </div>

      <div className="grid grid-cols-3 gap-4">
        <TokenStat label="cache read" value={cacheRead} tick="bg-teal/70" text="text-teal" />
        <TokenStat
          label="cache write"
          value={cacheCreation}
          tick="bg-lavender/70"
          text="text-lavender"
        />
        <TokenStat label="input" value={input} tick="bg-txt-3/60" text="text-txt" />
      </div>
    </div>
  );
}

export function TokenStat({
  label,
  value,
  tick,
  text,
  format = "tokens",
}: {
  label: string;
  value: number;
  tick: string;
  text: string;
  format?: "tokens" | "chars";
}) {
  const dim = value === 0;
  const display = dim
    ? "\u2014"
    : format === "chars"
      ? formatCompactChars(value)
      : value.toLocaleString();
  // "tokens" suffix renders only for the token format and only when we have
  // a real number to label. Chars intentionally stay bare per the convention
  // documented in the editor's "Why line items are in characters" panel.
  const showSuffix = format === "tokens" && !dim;
  return (
    <div className="flex items-baseline gap-2.5">
      <span className={`inline-block h-3 w-[2px] self-center ${dim ? "bg-edge-strong" : tick}`} />
      <span className="label shrink-0">{label}</span>
      <span
        className={`metric-num text-[14px] font-medium tracking-tight ${dim ? "text-txt-3" : text}`}
      >
        {display}
      </span>
      {showSuffix && <span className="label text-txt-3">tokens</span>}
    </div>
  );
}
