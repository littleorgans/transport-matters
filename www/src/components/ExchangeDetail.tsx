import { useEffect, useState } from "react";
import { fetchExchange } from "../api";
import type { ExchangeDetail as ExchangeDetailType } from "../types";

interface ExchangeDetailProps {
  id: string;
}

// ── Tool grouping ──────────────────────────────────────────────────

function pluginLabel(name: string): string {
  if (!name.startsWith("mcp__")) return "built-in";
  const parts = name.split("__");
  const pluginPart = parts[1] ?? "";
  return pluginPart.replace(/^plugin_/, "");
}

function shortName(name: string): string {
  if (!name.startsWith("mcp__")) return name;
  const parts = name.split("__");
  return parts[parts.length - 1] ?? name;
}

function groupTools(tools: Array<{ name: string }>): [string, string[]][] {
  const map: Record<string, string[]> = {};
  for (const t of tools) {
    const group = pluginLabel(t.name);
    if (!map[group]) map[group] = [];
    map[group].push(t.name);
  }
  // sort: built-in first, then alphabetically
  return Object.entries(map).sort(([a], [b]) => {
    if (a === "built-in") return -1;
    if (b === "built-in") return 1;
    return a.localeCompare(b);
  });
}

// A stable hue per plugin label so groups have consistent colour
const GROUP_HUES: Record<string, string> = {};
const PALETTE = [
  "text-sky-400 bg-sky-950/60 border-sky-900",
  "text-violet-400 bg-violet-950/60 border-violet-900",
  "text-emerald-400 bg-emerald-950/60 border-emerald-900",
  "text-amber-400 bg-amber-950/60 border-amber-900",
  "text-rose-400 bg-rose-950/60 border-rose-900",
  "text-teal-400 bg-teal-950/60 border-teal-900",
  "text-indigo-400 bg-indigo-950/60 border-indigo-900",
  "text-orange-400 bg-orange-950/60 border-orange-900",
];
let _paletteIdx = 0;

function groupColour(label: string): string {
  if (label === "built-in") return "text-zinc-300 bg-zinc-800/80 border-zinc-700";
  if (!GROUP_HUES[label]) {
    GROUP_HUES[label] = PALETTE[_paletteIdx % PALETTE.length] ?? PALETTE[0];
    _paletteIdx++;
  }
  return GROUP_HUES[label];
}

// ── Sub-components ─────────────────────────────────────────────────

function MetricCell({
  label,
  value,
  mono = true,
  accent,
}: {
  label: string;
  value: string | number;
  mono?: boolean;
  accent?: boolean;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] uppercase tracking-widest text-zinc-600">{label}</span>
      <span
        className={`text-sm leading-none ${mono ? "font-mono" : ""} ${accent ? "text-blue-300" : "text-zinc-100"}`}
      >
        {value}
      </span>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-2.5 flex items-center gap-2">
      <div className="h-px flex-1 bg-zinc-800" />
      <span className="text-[10px] uppercase tracking-widest text-zinc-600">{children}</span>
      <div className="h-px flex-1 bg-zinc-800" />
    </div>
  );
}

function ToolGroup({ label, names }: { label: string; names: string[] }) {
  const [open, setOpen] = useState(label === "built-in");
  const colour = groupColour(label);
  // label colour for the count badge (just the text part)
  const textCls = colour.split(" ")[0] ?? "text-zinc-300";

  return (
    <div className="rounded border border-zinc-800/70 bg-zinc-900/40">
      <button
        type="button"
        onClick={() => setOpen((p) => !p)}
        className="flex w-full cursor-pointer items-center justify-between px-3 py-1.5 text-left"
      >
        <span className="font-mono text-xs text-zinc-300">{label}</span>
        <span className={`font-mono text-xs tabular-nums ${textCls}`}>{names.length}</span>
      </button>

      {open && (
        <div className="border-t border-zinc-800/70 px-3 py-2">
          <div className="flex flex-wrap gap-1">
            {names.map((name) => (
              <span
                key={name}
                title={name}
                className={`rounded border px-1.5 py-0.5 font-mono text-[11px] ${colour}`}
              >
                {shortName(name)}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────

export function ExchangeDetail({ id }: ExchangeDetailProps) {
  const [detail, setDetail] = useState<ExchangeDetailType | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchExchange(id)
      .then((data) => {
        if (!cancelled) {
          setDetail(data);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load exchange");
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="flex items-center gap-2 text-xs text-zinc-600">
          <span className="inline-block h-1 w-1 animate-ping rounded-full bg-zinc-600" />
          loading
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="rounded border border-red-900/50 bg-red-950/30 px-3 py-2 text-xs text-red-400">
          {error}
        </p>
      </div>
    );
  }

  if (!detail) return null;

  const { entry, request_ir, response_ir } = detail;
  const tools = (request_ir.tools ?? []) as Array<{ name: string }>;
  const toolGroups = groupTools(tools);
  const pipeline = entry.pipeline;
  const saved = pipeline ? pipeline.chars_before - pipeline.chars_after : 0;
  const savedPct =
    pipeline && pipeline.chars_before > 0 ? Math.round((saved / pipeline.chars_before) * 100) : 0;

  const ts = new Date(entry.ts);
  const dateStr = ts.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
  const timeStr = ts.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* ── Sticky header ── */}
      <div className="border-b border-zinc-800 bg-zinc-950 px-4 py-3">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h2 className="truncate font-mono text-sm font-semibold text-zinc-100">
              {entry.model.replace(/^anthropic\//, "")}
            </h2>
            <div className="mt-0.5 flex items-center gap-2 text-xs text-zinc-600">
              <span className="rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-[10px] text-zinc-400">
                {entry.provider}
              </span>
              <span>{dateStr}</span>
              <span className="text-zinc-700">/</span>
              <span className="font-mono">{timeStr}</span>
              {entry.mutated_manually && (
                <span className="rounded bg-amber-950/50 px-1.5 py-0.5 text-[10px] text-amber-400 border border-amber-900/50">
                  edited
                </span>
              )}
            </div>
          </div>
          <span className="shrink-0 font-mono text-[10px] text-zinc-700 pt-0.5">
            {entry.id.slice(0, 8)}
          </span>
        </div>
      </div>

      {/* ── Scrollable body ── */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-5">
        {/* Request metrics */}
        <section>
          <SectionLabel>request</SectionLabel>
          <div className="grid grid-cols-4 gap-px rounded overflow-hidden border border-zinc-800/80 bg-zinc-800/40">
            {[
              { label: "sys parts", value: entry.req.system_parts },
              { label: "tools", value: entry.req.tools_count },
              { label: "messages", value: entry.req.messages_count },
              { label: "total", value: `${(entry.req.total_chars / 1024).toFixed(1)}KB` },
            ].map(({ label, value }) => (
              <div key={label} className="bg-zinc-950 px-3 py-2.5">
                <MetricCell label={label} value={value} />
              </div>
            ))}
          </div>
        </section>

        {/* Pipeline */}
        {pipeline && (
          <section>
            <SectionLabel>pipeline</SectionLabel>
            <div className="rounded border border-zinc-800/80 bg-zinc-950 overflow-hidden">
              <div className="grid grid-cols-3 gap-px bg-zinc-800/40">
                <div className="bg-zinc-950 px-3 py-2.5">
                  <MetricCell
                    label="before"
                    value={`${(pipeline.chars_before / 1024).toFixed(1)}KB`}
                  />
                </div>
                <div className="bg-zinc-950 px-3 py-2.5">
                  <MetricCell
                    label="after"
                    value={`${(pipeline.chars_after / 1024).toFixed(1)}KB`}
                  />
                </div>
                <div className="bg-zinc-950 px-3 py-2.5">
                  <MetricCell
                    label="saved"
                    value={saved > 0 ? `-${savedPct}%` : "—"}
                    accent={saved > 0}
                  />
                </div>
              </div>

              {/* Compression bar */}
              {pipeline.chars_before > 0 && (
                <div className="px-3 py-2 border-t border-zinc-800/60">
                  <div className="h-1 w-full rounded-full bg-zinc-800 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-blue-500/70 transition-all"
                      style={{ width: `${Math.max(2, 100 - savedPct)}%` }}
                    />
                  </div>
                </div>
              )}

              {pipeline.rules_applied.length > 0 && (
                <div className="border-t border-zinc-800/60 px-3 py-2 space-y-1">
                  {pipeline.rules_applied.map((r) => (
                    <div key={r.id} className="flex items-center justify-between gap-2 text-xs">
                      <span className="font-mono text-zinc-400">{r.name}</span>
                      <span className="text-[10px] rounded bg-zinc-800 px-1.5 py-0.5 text-zinc-500 font-mono">
                        {r.action}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>
        )}

        {/* Tools */}
        {tools.length > 0 && (
          <section>
            <SectionLabel>tools · {tools.length}</SectionLabel>
            <div className="space-y-1">
              {toolGroups.map(([label, names]) => (
                <ToolGroup key={label} label={label} names={names} />
              ))}
            </div>
          </section>
        )}

        {/* Response */}
        {entry.res && (
          <section>
            <SectionLabel>response</SectionLabel>
            <div className="rounded border border-zinc-800/80 bg-zinc-950 overflow-hidden">
              <div className="grid grid-cols-3 gap-px bg-zinc-800/40">
                <div className="bg-zinc-950 px-3 py-2.5">
                  <MetricCell label="input tkns" value={entry.res.input_tokens.toLocaleString()} />
                </div>
                <div className="bg-zinc-950 px-3 py-2.5">
                  <MetricCell
                    label="output tkns"
                    value={entry.res.output_tokens.toLocaleString()}
                  />
                </div>
                <div className="bg-zinc-950 px-3 py-2.5">
                  <MetricCell
                    label="stop"
                    value={entry.res.stop_reason ?? "—"}
                    mono={false}
                    accent={entry.res.stop_reason === "end_turn"}
                  />
                </div>
              </div>

              {/* Token proportion bar */}
              {entry.res.input_tokens + entry.res.output_tokens > 0 && (
                <div className="px-3 py-2 border-t border-zinc-800/60 space-y-1">
                  <div className="flex items-center gap-1.5 h-1.5 w-full rounded-full overflow-hidden bg-zinc-800">
                    {(() => {
                      const total = entry.res.input_tokens + entry.res.output_tokens;
                      const cachePct =
                        entry.res.cache_read_input_tokens > 0
                          ? Math.round((entry.res.cache_read_input_tokens / total) * 100)
                          : 0;
                      const inputPct = Math.round((entry.res.input_tokens / total) * 100);
                      const outputPct = 100 - inputPct;
                      return (
                        <>
                          {cachePct > 0 && (
                            <div
                              className="h-full bg-teal-700/70"
                              style={{ width: `${cachePct}%` }}
                              title={`cache read: ${entry.res.cache_read_input_tokens}`}
                            />
                          )}
                          <div
                            className="h-full bg-zinc-500/70"
                            style={{ width: `${inputPct - cachePct}%` }}
                            title={`input: ${entry.res.input_tokens}`}
                          />
                          <div
                            className="h-full bg-blue-500/70"
                            style={{ width: `${outputPct}%` }}
                            title={`output: ${entry.res.output_tokens}`}
                          />
                        </>
                      );
                    })()}
                  </div>
                  <div className="flex items-center gap-3 text-[10px] text-zinc-600">
                    <span className="flex items-center gap-1">
                      <span className="inline-block h-1.5 w-1.5 rounded-sm bg-zinc-500/70" />
                      input
                    </span>
                    <span className="flex items-center gap-1">
                      <span className="inline-block h-1.5 w-1.5 rounded-sm bg-blue-500/70" />
                      output
                    </span>
                    {entry.res.cache_read_input_tokens > 0 && (
                      <span className="flex items-center gap-1">
                        <span className="inline-block h-1.5 w-1.5 rounded-sm bg-teal-700/70" />
                        cache ({entry.res.cache_read_input_tokens.toLocaleString()})
                      </span>
                    )}
                    {entry.res.tool_calls > 0 && (
                      <span className="ml-auto">
                        {entry.res.tool_calls} tool {entry.res.tool_calls === 1 ? "call" : "calls"}
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>
          </section>
        )}

        {/* Raw IR — collapsible */}
        <section>
          <details>
            <summary className="cursor-pointer select-none">
              <SectionLabel>request ir ▸</SectionLabel>
            </summary>
            <pre className="mt-2 max-h-80 overflow-auto rounded border border-zinc-800/60 bg-zinc-900/60 p-3 text-[11px] leading-relaxed text-zinc-400">
              {JSON.stringify(request_ir, null, 2)}
            </pre>
          </details>
        </section>

        {response_ir && (
          <section>
            <details>
              <summary className="cursor-pointer select-none">
                <SectionLabel>response ir ▸</SectionLabel>
              </summary>
              <pre className="mt-2 max-h-80 overflow-auto rounded border border-zinc-800/60 bg-zinc-900/60 p-3 text-[11px] leading-relaxed text-zinc-400">
                {JSON.stringify(response_ir, null, 2)}
              </pre>
            </details>
          </section>
        )}

        {/* bottom padding */}
        <div className="h-4" />
      </div>
    </div>
  );
}
