import type { ExchangeDetail, InternalResponse, Message } from "../../types";
import { KeyValueRow, MetricCell, MetricGrid, MetricGridCell, Panel, SectionRule } from "./atoms";
import { blockKey, ContentBlockRow, RequestMessage } from "./ContentBlocks";
import { groupTools, ToolGroup } from "./ToolGroups";

interface InspectTabProps {
  detail: ExchangeDetail;
}

export function InspectTab({ detail }: InspectTabProps) {
  const { entry, response_ir } = detail;
  // Prefer the curated IR (pipeline + any breakpoint edits) — that's what
  // was actually sent to the provider and what produced the response below.
  // Falls back to the original IR when the request was not mutated.
  const effectiveRequest = detail.request_curated_ir ?? detail.request_ir;
  const tools = (effectiveRequest.tools ?? []) as Array<{ name: string }>;
  const toolGroups = groupTools(tools);
  const pipeline = entry.pipeline;
  const saved = pipeline ? pipeline.chars_before - pipeline.chars_after : 0;
  const savedPct =
    pipeline && pipeline.chars_before > 0 ? Math.round((saved / pipeline.chars_before) * 100) : 0;

  const requestMessages = (effectiveRequest.messages ?? []) as Message[];
  const responseData = response_ir as InternalResponse | null;
  const responseContent = responseData?.content ?? [];

  return (
    <div className="px-8 py-7 space-y-10">
      <ExchangeCard detail={detail} />

      {/* Request messages */}
      {requestMessages.length > 0 && (
        <section>
          <SectionRule>Messages &middot; {requestMessages.length}</SectionRule>
          <div className="space-y-3">
            {requestMessages.map((msg, idx) => {
              const key = `${msg.role}-${idx}-${msg.content.length}`;
              return <RequestMessage key={key} message={msg} />;
            })}
          </div>
        </section>
      )}

      {/* Response content */}
      {responseContent.length > 0 && (
        <section>
          <SectionRule>Response Content &middot; {responseContent.length}</SectionRule>
          <div className="card-flush">
            {responseContent.map((block, idx) => (
              <div key={blockKey(block, idx)}>
                <ContentBlockRow block={block} />
                {idx < responseContent.length - 1 && <div className="hairline-x mx-4" />}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Pipeline */}
      {pipeline && (
        <section>
          <SectionRule>Pipeline</SectionRule>
          <Panel>
            <MetricGrid cols={3}>
              <MetricGridCell>
                <MetricCell
                  label="before"
                  value={`${(pipeline.chars_before / 1024).toFixed(1)}K`}
                />
              </MetricGridCell>
              <MetricGridCell>
                <MetricCell label="after" value={`${(pipeline.chars_after / 1024).toFixed(1)}K`} />
              </MetricGridCell>
              <MetricGridCell>
                <MetricCell
                  label="saved"
                  value={saved > 0 ? `\u2212${savedPct}%` : "\u2014"}
                  accent={saved > 0 ? "text-sage" : "text-txt-3"}
                />
              </MetricGridCell>
            </MetricGrid>

            {pipeline.chars_before > 0 && (
              <>
                <div className="hairline-x" />
                <div className="px-5 py-4">
                  <CompressionBar savedPct={savedPct} />
                </div>
              </>
            )}

            {pipeline.rules_applied.length > 0 && (
              <>
                <div className="hairline-x" />
                <div className="px-5 py-3">
                  {pipeline.rules_applied.map((r) => (
                    <KeyValueRow
                      key={r.id}
                      label={r.name}
                      value={
                        <span className="border border-edge bg-canvas px-2 py-0.5 text-[9px] uppercase tracking-wider text-txt-2">
                          {r.action}
                        </span>
                      }
                      valueClass=""
                    />
                  ))}
                </div>
              </>
            )}
          </Panel>
        </section>
      )}

      {/* Tools */}
      {tools.length > 0 && (
        <section>
          <SectionRule>Tools &middot; {tools.length}</SectionRule>
          <div className="space-y-2">
            {toolGroups.map(([label, names]) => (
              <ToolGroup key={label} label={label} names={names} />
            ))}
          </div>
        </section>
      )}

      <div className="h-8" />
    </div>
  );
}

// ── Exchange card ──────────────────────────────────────────────────
// One card, three sections: header (outcome chips), tokens (hero
// bar + three numbers), meta (sys parts / tools / messages). When
// the response hasn't arrived yet the token section collapses and
// the header shows an "awaiting response" pulse dot.

function ExchangeCard({ detail }: { detail: ExchangeDetail }) {
  const { entry } = detail;
  const res = entry.res;
  const tokenTotal = res ? res.input_tokens + res.output_tokens + res.cache_read_input_tokens : 0;
  const showTokens = !!res && tokenTotal > 0;

  return (
    <div className="card top-highlight">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 px-5 py-3">
        <div className="flex items-center gap-2.5">
          <span className="inline-block h-3 w-px bg-sky/50" />
          <span className="label">Exchange</span>
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
            <span className="inline-block h-1.5 w-1.5 bg-sky/70 pulse-dot" />
            <span className="label">awaiting response</span>
          </span>
        )}
      </div>

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
        <MetaStat value={entry.req.system_parts} label="sys parts" />
        <MetaStat value={entry.req.tools_count} label="tools" />
        <MetaStat value={entry.req.messages_count} label="messages" />
      </div>
    </div>
  );
}

function MetaStat({ value, label }: { value: number; label: string }) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="metric-num text-[11px] text-txt-2">{value}</span>
      <span className="label">{label}</span>
    </span>
  );
}

// ── Token bar ──────────────────────────────────────────────────────
// Three buckets summing to 100: cache, non-cached input, output.
// The bar itself is a recessed channel; three fixed columns of
// numbers sit below it, each introduced by a 2px accent tick that
// matches the segment colour so the eye can thread bar to number.

function TokenBar({ input, output, cache }: { input: number; output: number; cache: number }) {
  const total = input + output + cache;
  if (total === 0) return null;
  const cachePct = (cache / total) * 100;
  const inputPct = (input / total) * 100;
  const outputPct = (output / total) * 100;

  return (
    <div className="space-y-4">
      <div
        className="flex h-2.5 w-full overflow-hidden bg-canvas"
        style={{
          boxShadow: "inset 0 1px 2px 0 rgba(0,0,0,0.6), inset 0 -1px 0 0 rgba(255,255,255,0.03)",
        }}
      >
        {cache > 0 && (
          <div
            className="h-full bg-teal/70"
            style={{ width: `${cachePct}%` }}
            title={`cache: ${cache.toLocaleString()}`}
          />
        )}
        {input > 0 && (
          <div
            className="h-full bg-txt-3/60"
            style={{ width: `${inputPct}%` }}
            title={`input: ${input.toLocaleString()}`}
          />
        )}
        {output > 0 && (
          <div
            className="h-full bg-sky/80"
            style={{ width: `${outputPct}%` }}
            title={`output: ${output.toLocaleString()}`}
          />
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

function TokenStat({
  label,
  value,
  tick,
  text,
}: {
  label: string;
  value: number;
  tick: string;
  text: string;
}) {
  const dim = value === 0;
  return (
    <div className="flex items-baseline gap-2.5">
      <span className={`inline-block h-3 w-[2px] self-center ${dim ? "bg-edge-strong" : tick}`} />
      <span className="label shrink-0">{label}</span>
      <span
        className={`metric-num text-[14px] font-medium tracking-tight ${dim ? "text-txt-3" : text}`}
      >
        {dim ? "\u2014" : value.toLocaleString()}
      </span>
    </div>
  );
}

// ── Compression bar ────────────────────────────────────────────────
// Shows how much of the original prompt survived the pipeline.

function CompressionBar({ savedPct }: { savedPct: number }) {
  const remaining = Math.max(2, 100 - savedPct);
  return (
    <div className="space-y-2">
      <div
        className="h-1 w-full bg-canvas overflow-hidden"
        style={{ boxShadow: "inset 0 1px 0 0 rgba(0,0,0,0.5)" }}
      >
        <div
          className="h-full bg-gradient-to-r from-lavender/60 to-lavender/30 transition-all"
          style={{ width: `${remaining}%` }}
        />
      </div>
      <div className="flex items-center justify-between label">
        <span>remaining {remaining}%</span>
        {savedPct > 0 && <span className="text-sage">{savedPct}% saved</span>}
      </div>
    </div>
  );
}
