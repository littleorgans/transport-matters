import { HoverCard } from "../HoverCard";

export function TokenBar({
  input,
  output,
  cache,
}: {
  input: number;
  output: number;
  cache: number;
}) {
  const total = input + output + cache;
  if (total === 0) return null;
  const cachePct = (cache / total) * 100;
  const inputPct = (input / total) * 100;
  const outputPct = (output / total) * 100;

  return (
    <div className="space-y-4">
      <div className="flex h-2.5 w-full overflow-hidden bg-canvas bar-track">
        {cache > 0 && (
          <HoverCard
            content={
              <span>
                <span className="text-teal">cache</span> {cache.toLocaleString()} (
                {cachePct.toFixed(1)}%)
              </span>
            }
          >
            <div className="h-full bg-teal/70" style={{ width: `${cachePct}%` }} />
          </HoverCard>
        )}
        {input > 0 && (
          <HoverCard
            content={
              <span>
                <span className="text-txt">input</span> {input.toLocaleString()} (
                {inputPct.toFixed(1)}%)
              </span>
            }
          >
            <div className="h-full bg-txt-3/60" style={{ width: `${inputPct}%` }} />
          </HoverCard>
        )}
        {output > 0 && (
          <HoverCard
            content={
              <span>
                <span className="text-sky">output</span> {output.toLocaleString()} (
                {outputPct.toFixed(1)}%)
              </span>
            }
          >
            <div className="h-full bg-sky/80" style={{ width: `${outputPct}%` }} />
          </HoverCard>
        )}
      </div>

      <div className="grid grid-cols-3 gap-4">
        <TokenStat label="cache" value={cache} tick="bg-teal/70" text="text-teal" />
        <TokenStat label="input" value={input} tick="bg-txt-3/60" text="text-txt" />
        <TokenStat label="output" value={output} tick="bg-sky/80" text="text-sky" />
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
    : format === "chars" && value >= 1024
      ? `${(value / 1024).toFixed(1)}K`
      : value.toLocaleString();
  return (
    <div className="flex items-baseline gap-2.5">
      <span className={`inline-block h-3 w-[2px] self-center ${dim ? "bg-edge-strong" : tick}`} />
      <span className="label shrink-0">{label}</span>
      <span
        className={`metric-num text-[14px] font-medium tracking-tight ${dim ? "text-txt-3" : text}`}
      >
        {display}
      </span>
    </div>
  );
}
