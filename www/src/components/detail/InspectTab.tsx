import { useState } from "react";
import type { ContentBlock, ExchangeDetail, InternalResponse, Message } from "../../types";

interface InspectTabProps {
  detail: ExchangeDetail;
}

// ── Shared sub-components ──────────────────────────────────────────

function MetricCell({
  label,
  value,
  accent,
}: {
  label: string;
  value: string | number;
  accent?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[9px] uppercase tracking-[0.12em] text-txt-3">{label}</span>
      <span className={`text-[13px] leading-none tabular-nums ${accent ?? "text-txt"}`}>
        {value}
      </span>
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 mb-3">
      <div className="h-px flex-1 bg-edge" />
      <span className="text-[9px] uppercase tracking-[0.14em] text-txt-3 font-medium">
        {children}
      </span>
      <div className="h-px flex-1 bg-edge" />
    </div>
  );
}

// ── Tool grouping ──────────────────────────────────────────────────

function pluginLabel(name: string): string {
  if (!name.startsWith("mcp__")) return "built-in";
  const parts = name.split("__");
  return (parts[1] ?? "").replace(/^plugin_/, "");
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
  return Object.entries(map).sort(([a], [b]) => {
    if (a === "built-in") return -1;
    if (b === "built-in") return 1;
    return a.localeCompare(b);
  });
}

const GROUP_HUES: Record<string, string> = {};
const PALETTE = [
  "text-sky bg-sky/8 border-sky/15",
  "text-lavender bg-lavender/8 border-lavender/15",
  "text-sage bg-sage/8 border-sage/15",
  "text-amber bg-amber/8 border-amber/15",
  "text-rose bg-rose/8 border-rose/15",
  "text-teal bg-teal/8 border-teal/15",
];
let _paletteIdx = 0;

function groupColour(label: string): string {
  if (label === "built-in") return "text-txt-2 bg-raised border-edge";
  const existing = GROUP_HUES[label];
  if (existing) return existing;
  const colour = PALETTE[_paletteIdx % PALETTE.length] as string;
  GROUP_HUES[label] = colour;
  _paletteIdx++;
  return colour;
}

function ToolGroup({ label, names }: { label: string; names: string[] }) {
  const [open, setOpen] = useState(false);
  const colour = groupColour(label);
  const textCls = colour.split(" ")[0] ?? "text-txt-2";

  return (
    <div className="rounded-md border border-edge bg-surface">
      <button
        type="button"
        onClick={() => setOpen((p) => !p)}
        className="flex w-full cursor-pointer items-center justify-between px-4 py-2.5 text-left"
      >
        <span className="text-[11px] text-txt-2">{label}</span>
        <span className={`text-[11px] tabular-nums ${textCls}`}>{names.length}</span>
      </button>

      {open && (
        <div className="border-t border-edge px-4 py-3">
          <div className="flex flex-wrap gap-1.5">
            {names.map((name) => (
              <span
                key={name}
                title={name}
                className={`rounded-md border px-2 py-1 text-[10px] ${colour}`}
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

// ── Response content rendering ─────────────────────────────────────

function blockSummary(block: ContentBlock): string {
  switch (block.type) {
    case "text":
      return block.text.slice(0, 200) + (block.text.length > 200 ? "..." : "");
    case "tool_use":
      return `${block.name}(${block.id.slice(0, 8)})`;
    case "tool_result":
      return `result for ${block.tool_use_id.slice(0, 8)}${block.is_error ? " [error]" : ""}`;
    case "thinking":
      return `${block.text.length.toLocaleString()} chars of reasoning`;
    case "image":
      return "image";
    case "unknown":
      return "unknown block";
  }
}

const BLOCK_ACCENT: Record<string, string> = {
  text: "border-l-sky/40",
  tool_use: "border-l-lavender/40",
  tool_result: "border-l-teal/40",
  thinking: "border-l-amber/40",
  image: "border-l-rose/40",
  unknown: "border-l-edge",
};

function ResponseContentBlock({ block }: { block: ContentBlock }) {
  const [expanded, setExpanded] = useState(false);
  const accent = BLOCK_ACCENT[block.type] ?? "border-l-edge";

  return (
    <div className={`border-l-2 ${accent} pl-3 py-2`}>
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full cursor-pointer items-start gap-2 text-left"
      >
        <span className="shrink-0 rounded bg-raised px-1.5 py-0.5 text-[9px] uppercase text-txt-3">
          {block.type}
        </span>
        <span className="text-[11px] text-txt-2 truncate">{blockSummary(block)}</span>
      </button>
      {expanded && (
        <pre className="mt-2 max-h-64 overflow-auto rounded-md bg-canvas p-3 text-[10px] leading-relaxed text-txt-2 whitespace-pre-wrap">
          {block.type === "text" || block.type === "thinking"
            ? block.text
            : JSON.stringify(block, null, 2)}
        </pre>
      )}
    </div>
  );
}

// ── Request message rendering ──────────────────────────────────────

const ROLE_STYLE: Record<string, string> = {
  user: "text-sky bg-sky/8",
  assistant: "text-sage bg-sage/8",
};

function RequestMessage({ message }: { message: Message }) {
  return (
    <div className="rounded-md border border-edge overflow-hidden">
      <div className="flex items-center gap-2 px-3 py-2 bg-surface">
        <span
          className={`rounded px-2 py-0.5 text-[9px] font-medium uppercase ${ROLE_STYLE[message.role] ?? "text-txt-2 bg-raised"}`}
        >
          {message.role}
        </span>
        <span className="text-[10px] text-txt-3">
          {message.content.length} block{message.content.length !== 1 ? "s" : ""}
        </span>
      </div>
      <div className="space-y-0">
        {message.content.map((block) => {
          const key =
            block.type === "tool_use"
              ? block.id
              : block.type === "tool_result"
                ? `result-${block.tool_use_id}`
                : `${block.type}-${JSON.stringify(block).length}`;
          return (
            <div key={key} className="border-t border-edge-subtle">
              <ResponseContentBlock block={block} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Main inspect tab ───────────────────────────────────────────────

export function InspectTab({ detail }: InspectTabProps) {
  const { entry, request_ir, response_ir } = detail;
  const tools = (request_ir.tools ?? []) as Array<{ name: string }>;
  const toolGroups = groupTools(tools);
  const pipeline = entry.pipeline;
  const saved = pipeline ? pipeline.chars_before - pipeline.chars_after : 0;
  const savedPct =
    pipeline && pipeline.chars_before > 0 ? Math.round((saved / pipeline.chars_before) * 100) : 0;

  // Parse IR content for rendering
  const requestMessages = (request_ir.messages ?? []) as Message[];
  const responseData = response_ir as InternalResponse | null;
  const responseContent = responseData?.content ?? [];

  return (
    <div className="px-6 py-6 space-y-8">
      {/* Request + Response metrics side by side */}
      <div className="grid grid-cols-2 gap-6">
        {/* Request metrics */}
        <section>
          <SectionLabel>Request</SectionLabel>
          <div className="grid grid-cols-2 gap-px rounded-md overflow-hidden border border-edge bg-edge">
            {[
              { label: "sys parts", value: entry.req.system_parts },
              { label: "tools", value: entry.req.tools_count },
              { label: "messages", value: entry.req.messages_count },
              { label: "payload", value: `${(entry.req.total_chars / 1024).toFixed(1)}K` },
            ].map(({ label, value }) => (
              <div key={label} className="bg-surface px-4 py-3.5">
                <MetricCell label={label} value={value} />
              </div>
            ))}
          </div>
        </section>

        {/* Response metrics */}
        <section>
          <SectionLabel>Response</SectionLabel>
          {entry.res ? (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-px rounded-md overflow-hidden border border-edge bg-edge">
                {[
                  {
                    label: "input",
                    value: entry.res.input_tokens.toLocaleString(),
                    accent: undefined,
                  },
                  {
                    label: "output",
                    value: entry.res.output_tokens.toLocaleString(),
                    accent: "text-sky",
                  },
                  {
                    label: "cache",
                    value:
                      entry.res.cache_read_input_tokens > 0
                        ? entry.res.cache_read_input_tokens.toLocaleString()
                        : "\u2014",
                    accent: entry.res.cache_read_input_tokens > 0 ? "text-teal" : undefined,
                  },
                  {
                    label: "stop",
                    value: entry.res.stop_reason ?? "\u2014",
                    accent: entry.res.stop_reason === "end_turn" ? "text-sage" : undefined,
                  },
                ].map(({ label, value, accent }) => (
                  <div key={label} className="bg-surface px-4 py-3.5">
                    <MetricCell label={label} value={value} accent={accent} />
                  </div>
                ))}
              </div>

              {/* Token proportion bar */}
              {entry.res.input_tokens + entry.res.output_tokens > 0 && (
                <div className="space-y-2">
                  <div className="flex h-1.5 w-full rounded-full overflow-hidden bg-raised">
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
                              className="h-full bg-teal/50"
                              style={{ width: `${cachePct}%` }}
                              title={`cache: ${entry.res.cache_read_input_tokens}`}
                            />
                          )}
                          <div
                            className="h-full bg-txt-3/50"
                            style={{ width: `${Math.max(1, inputPct - cachePct)}%` }}
                            title={`input: ${entry.res.input_tokens}`}
                          />
                          <div
                            className="h-full bg-sky/50"
                            style={{ width: `${outputPct}%` }}
                            title={`output: ${entry.res.output_tokens}`}
                          />
                        </>
                      );
                    })()}
                  </div>
                  <div className="flex items-center gap-4 text-[9px] text-txt-3">
                    <span className="flex items-center gap-1.5">
                      <span className="inline-block h-1.5 w-1.5 rounded-sm bg-txt-3/50" />
                      input
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span className="inline-block h-1.5 w-1.5 rounded-sm bg-sky/50" />
                      output
                    </span>
                    {entry.res.cache_read_input_tokens > 0 && (
                      <span className="flex items-center gap-1.5">
                        <span className="inline-block h-1.5 w-1.5 rounded-sm bg-teal/50" />
                        cache
                      </span>
                    )}
                    {entry.res.tool_calls > 0 && (
                      <span className="ml-auto tabular-nums">
                        {entry.res.tool_calls} tool call{entry.res.tool_calls === 1 ? "" : "s"}
                      </span>
                    )}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="flex items-center justify-center rounded-md border border-edge bg-surface px-4 py-6">
              <span className="text-[11px] text-txt-3">Awaiting response</span>
            </div>
          )}
        </section>
      </div>

      {/* Request messages */}
      {requestMessages.length > 0 && (
        <section>
          <SectionLabel>Messages ({requestMessages.length})</SectionLabel>
          <div className="space-y-2">
            {requestMessages.map((msg) => {
              const key = `${msg.role}-${msg.content.length}-${JSON.stringify(msg.content[0] ?? "").length}`;
              return <RequestMessage key={key} message={msg} />;
            })}
          </div>
        </section>
      )}

      {/* Pipeline */}
      {pipeline && (
        <section>
          <SectionLabel>Pipeline</SectionLabel>
          <div className="rounded-md border border-edge bg-surface overflow-hidden">
            <div className="grid grid-cols-3 gap-px bg-edge">
              <div className="bg-surface px-4 py-3.5">
                <MetricCell
                  label="before"
                  value={`${(pipeline.chars_before / 1024).toFixed(1)}K`}
                />
              </div>
              <div className="bg-surface px-4 py-3.5">
                <MetricCell label="after" value={`${(pipeline.chars_after / 1024).toFixed(1)}K`} />
              </div>
              <div className="bg-surface px-4 py-3.5">
                <MetricCell
                  label="saved"
                  value={saved > 0 ? `\u2212${savedPct}%` : "\u2014"}
                  accent={saved > 0 ? "text-sage" : undefined}
                />
              </div>
            </div>

            {pipeline.chars_before > 0 && (
              <div className="px-4 py-3 border-t border-edge">
                <div className="h-1 w-full rounded-full bg-raised overflow-hidden">
                  <div
                    className="h-full rounded-full bg-lavender/40 transition-all"
                    style={{ width: `${Math.max(2, 100 - savedPct)}%` }}
                  />
                </div>
              </div>
            )}

            {pipeline.rules_applied.length > 0 && (
              <div className="border-t border-edge px-4 py-3 space-y-1.5">
                {pipeline.rules_applied.map((r) => (
                  <div key={r.id} className="flex items-center justify-between gap-3 text-[11px]">
                    <span className="text-txt-2">{r.name}</span>
                    <span className="rounded bg-raised px-2 py-0.5 text-[10px] text-txt-3">
                      {r.action}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>
      )}

      {/* Response content blocks */}
      {responseContent.length > 0 && (
        <section>
          <SectionLabel>Response Content</SectionLabel>
          <div className="space-y-1">
            {responseContent.map((block) => {
              const key =
                block.type === "tool_use"
                  ? block.id
                  : block.type === "tool_result"
                    ? `result-${block.tool_use_id}`
                    : `${block.type}-${JSON.stringify(block).length}`;
              return <ResponseContentBlock key={key} block={block} />;
            })}
          </div>
        </section>
      )}

      {/* Tools */}
      {tools.length > 0 && (
        <section>
          <SectionLabel>Tools ({tools.length})</SectionLabel>
          <div className="space-y-1.5">
            {toolGroups.map(([label, names]) => (
              <ToolGroup key={label} label={label} names={names} />
            ))}
          </div>
        </section>
      )}

      {/* Bottom breathing room */}
      <div className="h-6" />
    </div>
  );
}
