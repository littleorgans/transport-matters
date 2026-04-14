import { useState } from "react";
import type { ExchangeDetail, Message, OverrideAuditEntry } from "../../types";
import { CompressionBar } from "./CompressionBar";
import { countContentBlocks } from "./ContentBlocks";
import { TokenBar, TokenStat } from "./TokenBar";

export function ExchangeCard({ detail }: { detail: ExchangeDetail }) {
  const { entry } = detail;
  const res = entry.res;
  const pipeline = entry.pipeline;
  const totalBefore =
    pipeline?.chars_before ?? (detail.request_ir ? JSON.stringify(detail.request_ir).length : 0);
  const totalAfter =
    pipeline?.chars_after ??
    (detail.request_curated_ir ? JSON.stringify(detail.request_curated_ir).length : 0);
  const saved = totalBefore - totalAfter;
  const savedPct = totalBefore > 0 ? Math.round((saved / totalBefore) * 100) : 0;
  const effectiveMessages = ((detail.request_curated_ir ?? detail.request_ir).messages ??
    []) as Message[];
  const hasPipelineSavings =
    saved > 0 || (pipeline?.overrides_applied.length ?? 0) > 0 || entry.mutated_manually;

  type CardTab = "exchange" | "pipeline";
  const [cardTab, setCardTab] = useState<CardTab>("exchange");

  const tokenTotal = res ? res.input_tokens + res.output_tokens + res.cache_read_input_tokens : 0;
  const showTokens = !!res && tokenTotal > 0;

  return (
    <div className="card top-highlight">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 px-5 py-3">
        <div className="flex items-center gap-2.5">
          <span
            className={`inline-block h-3 w-px transition-colors ${
              cardTab === "exchange" ? "bg-accent/50" : "bg-sage/50"
            }`}
          />
          <button
            type="button"
            onClick={() => setCardTab("exchange")}
            className={`text-[11px] font-medium uppercase tracking-[0.14em] cursor-pointer transition-colors ${
              cardTab === "exchange" ? "text-txt" : "text-txt-3 hover:text-txt-2"
            }`}
          >
            Exchange
          </button>
          {hasPipelineSavings && (
            <>
              <span className="text-txt-3 text-[11px]">&middot;</span>
              <button
                type="button"
                onClick={() => setCardTab("pipeline")}
                className={`text-[11px] font-medium uppercase tracking-[0.14em] cursor-pointer transition-colors ${
                  cardTab === "pipeline" ? "text-sage" : "text-txt-3 hover:text-txt-2"
                }`}
              >
                Pipeline
                <span className="ml-1.5 text-sage">&minus;{savedPct}%</span>
              </button>
            </>
          )}
        </div>
        {res ? (
          <div className="flex items-center gap-2">
            {res.stop_reason && (
              <span
                className={`chip ${res.stop_reason === "end_turn" ? "text-sage" : "text-amber"}`}
              >
                {res.stop_reason}
              </span>
            )}
            {res.tool_calls > 0 && (
              <span className="chip text-lavender">
                {res.tool_calls} tool call{res.tool_calls !== 1 ? "s" : ""}
              </span>
            )}
          </div>
        ) : (
          <span className="flex items-center gap-2">
            <span className="inline-block h-1.5 w-1.5 bg-accent/70 pulse-dot" />
            <span className="label">awaiting response</span>
          </span>
        )}
      </div>

      {cardTab === "exchange" ? (
        <>
          {/* Tokens (hero) */}
          {showTokens && res && (
            <>
              <div className="hairline-x" />
              <div className="px-6 py-5">
                <TokenBar
                  input={res.input_tokens}
                  output={res.output_tokens}
                  cache={res.cache_read_input_tokens}
                />
              </div>
            </>
          )}

          {/* Meta */}
          <div className="hairline-x" />
          <div className="flex items-center gap-6 px-5 py-2.5">
            <MetaStat value={entry.req.system_parts} label="system messages" />
            <MetaStat value={entry.req.tools_count} label="tools" />
            <MetaStat value={countContentBlocks(effectiveMessages)} label="messages" />
          </div>
        </>
      ) : (
        <>
          {/* Compression bar (only when pipeline has data) */}
          {saved > 0 && (
            <>
              <div className="hairline-x" />
              <div className="px-6 py-5">
                <div className="space-y-4">
                  <CompressionBar savedPct={savedPct} before={totalBefore} after={totalAfter} />
                  <div className="grid grid-cols-3 gap-4">
                    <TokenStat
                      label="before"
                      value={totalBefore}
                      tick="bg-txt-3/60"
                      text="text-txt"
                      format="chars"
                    />
                    <TokenStat
                      label="after"
                      value={totalAfter}
                      tick="bg-lavender/60"
                      text="text-lavender"
                      format="chars"
                    />
                    <TokenStat
                      label="saved"
                      value={saved}
                      tick="bg-sage/60"
                      text="text-sage"
                      format="chars"
                    />
                  </div>
                </div>
              </div>
            </>
          )}

          {/* Overrides applied */}
          <div className="hairline-x" />
          <div className="flex items-center gap-6 px-5 py-2.5">
            {pipeline && pipeline.overrides_applied.length > 0 ? (
              groupOverridesByKind(pipeline.overrides_applied).map((g) => (
                <span
                  key={g.kind}
                  className={`flex items-baseline gap-1.5 ${g.appliedCount > 0 ? "" : "opacity-40"}`}
                >
                  <span className="chip text-txt-3">{g.kind}</span>
                  {g.count > 1 && (
                    <span className="text-[11px] text-txt-3 metric-num">&times;{g.count}</span>
                  )}
                  {g.delta !== 0 && (
                    <span
                      className={`text-[11px] metric-num ${g.delta < 0 ? "text-sage" : "text-amber"}`}
                    >
                      {g.delta < 0 ? "\u2212" : "+"}
                      {Math.abs(g.delta).toLocaleString()}
                    </span>
                  )}
                </span>
              ))
            ) : (
              <span className="text-[11px] font-medium uppercase tracking-[0.14em] text-txt-3">
                no overrides applied
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function MetaStat({ value, label }: { value: number; label: string }) {
  const display = value === 1 ? label.replace(/s$/, "") : label;
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="metric-num text-[13px] text-txt-2">{value}</span>
      <span className="label">{display}</span>
    </span>
  );
}

interface OverrideGroup {
  kind: string;
  count: number;
  appliedCount: number;
  delta: number;
}

// Collapse per-target audit entries into one row per kind. A single paused
// flow can emit dozens of `tool_toggle` / `message_block_toggle` entries;
// rendering each as its own chip buries the summary under identical labels.
function groupOverridesByKind(entries: OverrideAuditEntry[]): OverrideGroup[] {
  const byKind = new Map<string, OverrideGroup>();
  for (const e of entries) {
    const g = byKind.get(e.kind) ?? { kind: e.kind, count: 0, appliedCount: 0, delta: 0 };
    g.count += 1;
    if (e.applied) {
      g.appliedCount += 1;
      g.delta += e.chars_delta;
    }
    byKind.set(e.kind, g);
  }
  return Array.from(byKind.values());
}
