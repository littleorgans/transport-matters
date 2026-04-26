import { useQuery } from "@tanstack/react-query";
import { startTransition, useDeferredValue, useEffect, useState } from "react";
import { fetchExchange } from "../api";
import { useMeta } from "../hooks/useMeta";
import { displayCwd, displayModel } from "../lib/formatting";
import { useUIStore } from "../stores/uiStore";
import type { ExchangeDetail as ExchangeDetailPayload, TransportDiagnostic } from "../types";
import { CodexTransportPanel } from "./detail/CodexTransportPanel";
import { InspectTab } from "./detail/InspectTab";
import { JsonView } from "./detail/JsonView";

interface ExchangeDetailProps {
  id: string;
}

type DetailTab = "inspect" | "request" | "response" | "transport";

function hasCodexTimeline(detail: ExchangeDetailPayload): boolean {
  return detail.entry.provider === "codex" && detail.events != null && detail.turn != null;
}

function inspectTabLabel(detail: ExchangeDetailPayload): string {
  return hasCodexTimeline(detail) ? "timeline" : "inspect";
}

function codexTurnTone(status: NonNullable<ExchangeDetailPayload["turn"]>["status"]): string {
  if (status === "completed") return "text-sage";
  if (status === "failed") return "text-rose";
  if (status === "interrupted") return "text-lavender";
  return "text-amber";
}

interface HeaderTelemetryChip {
  text: string;
  tone?: string;
}

function codexHeaderTelemetry(detail: ExchangeDetailPayload): HeaderTelemetryChip[] {
  if (detail.turn == null) {
    return [];
  }
  const chips: HeaderTelemetryChip[] = [
    {
      text: `turn ${detail.turn.turn_index} ${detail.turn.status}`,
      tone: codexTurnTone(detail.turn.status),
    },
    {
      text: `frames ${detail.turn.message_range_start} to ${detail.turn.message_range_end}`,
    },
    {
      text: `${detail.turn.text_chars.toLocaleString()} chars`,
      tone: "text-sky",
    },
  ];
  if (detail.turn.tool_calls > 0) {
    chips.push({
      text: `${detail.turn.tool_calls.toLocaleString()} tool ${
        detail.turn.tool_calls === 1 ? "call" : "calls"
      }`,
    });
  }
  return chips;
}

/**
 * Per-tab readout. Turns the INSPECT|REQUEST|RESPONSE bar from a label row
 * into the second deck of the instrument panel the header above establishes:
 * each cell carries a label and a contextual metric rather than just a name.
 *
 * Unit choices follow the tokens-vs-chars rule — show real tokens when the
 * payload has them, raw chars otherwise, no heuristic conversion. Returns
 * null when there's nothing meaningful to render so the readout line stays
 * absent instead of fake-empty.
 */
function tabReadout(t: DetailTab, detail: ExchangeDetailPayload): string | null {
  const { entry, response_ir, transport } = detail;

  if (t === "inspect") {
    if (hasCodexTimeline(detail)) {
      const eventCount = detail.events?.length ?? 0;
      const status = detail.turn?.status === "open" ? "live" : detail.turn?.status;
      return status
        ? `${eventCount.toLocaleString()} events · ${status}`
        : `${eventCount.toLocaleString()} events`;
    }
    const n = entry.req?.messages_count ?? 0;
    if (!n) return null;
    return `${n.toLocaleString()} ${n === 1 ? "message" : "messages"}`;
  }

  if (t === "request") {
    if (entry.res) {
      const ctx =
        (entry.res.input_tokens ?? 0) +
        (entry.res.cache_creation_input_tokens ?? 0) +
        (entry.res.cache_read_input_tokens ?? 0);
      if (ctx > 0) return `${ctx.toLocaleString()} tokens`;
    }
    const chars = entry.req?.total_chars ?? 0;
    return chars > 0 ? `${chars.toLocaleString()} chars` : null;
  }

  if (t === "transport") {
    const frames = transport?.messages.length ?? 0;
    if (frames === 0) return null;
    return `${frames.toLocaleString()} ${frames === 1 ? "frame" : "frames"}`;
  }

  // response — em dash when there's no payload, so the dimmed tab reads
  // as "no channel here" instead of ambiguously empty.
  if (!response_ir || !entry.res) return "\u2014";
  const out = entry.res.output_tokens ?? 0;
  return out > 0 ? `${out.toLocaleString()} tokens` : "\u2014";
}

function TransportDiagnostics({ diagnostics }: { diagnostics: TransportDiagnostic[] }) {
  if (diagnostics.length === 0) {
    return null;
  }

  const toneClass = (severity: TransportDiagnostic["severity"]): string => {
    if (severity === "error") return "border-rose/30 bg-rose/8 text-rose";
    if (severity === "warning") return "border-amber/30 bg-amber/8 text-amber";
    return "border-sky/30 bg-sky/8 text-sky";
  };

  return (
    <section className="px-8 py-6">
      <div className="space-y-3">
        {diagnostics.map((diagnostic) => (
          <div
            key={diagnostic.code}
            className={`rounded-md border px-4 py-3 ${toneClass(diagnostic.severity)}`}
          >
            <div className="flex items-center gap-2">
              <span className="text-[11px] uppercase tracking-[0.14em]">{diagnostic.severity}</span>
              <span className="text-[11px] text-txt-3">{diagnostic.code}</span>
            </div>
            <p className="mt-2 text-[13px] font-medium text-txt">{diagnostic.summary}</p>
            {diagnostic.detail && (
              <p className="mt-1 text-[12px] text-txt-2">{diagnostic.detail}</p>
            )}
            {diagnostic.operator_checks.length > 0 && (
              <div className="mt-3 space-y-1">
                {diagnostic.operator_checks.map((check) => (
                  <p key={check} className="text-[12px] text-txt-2">
                    {check}
                  </p>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

export function ExchangeDetail({ id }: ExchangeDetailProps) {
  const [tab, setTab] = useState<DetailTab>("inspect");
  const deferredTab = useDeferredValue(tab);
  const [transportFocus, setTransportFocus] = useState<{
    exchangeId: string;
    messageIndex: number;
  } | null>(null);
  const { meta } = useMeta();

  const {
    data: detail,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["exchange", id],
    queryFn: () => fetchExchange(id),
    retry: false,
  });

  // Clear stale selection if the exchange no longer exists (e.g., storage wiped)
  useEffect(() => {
    if (error && error instanceof Error && error.message.includes("404")) {
      useUIStore.getState().setSelectedId(null);
    }
  }, [error]);

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="flex items-center gap-2.5">
          <span className="inline-block h-1 w-1 rounded-full bg-accent pulse-dot" />
          <span className="label">Loading exchange</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="border border-rose/25 bg-rose/5 px-4 py-2.5 text-[13px] text-rose">
          {error instanceof Error ? error.message : "Failed to load exchange"}
        </p>
      </div>
    );
  }

  if (!detail) return null;

  const { entry } = detail;
  const inspectLabel = inspectTabLabel(detail);
  const headerTelemetry = codexHeaderTelemetry(detail);
  const ts = new Date(entry.ts);
  const dateStr = ts.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
  const timeStr = ts.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  return (
    <div className="flex h-full flex-col overflow-hidden fade-in">
      {/* Header: shared archive identity with an optional provider
          telemetry row. Codex gets transport state without forcing every
          metadata item into equal-width instrument cells. */}
      <div className="top-highlight">
        <div className="px-7 py-5">
          <div className="flex min-w-0 items-start justify-between gap-6">
            <div className="min-w-0 flex-1">
              <h2 className="metric-num truncate text-[22px] font-semibold uppercase leading-none tracking-[0.1em] text-txt">
                {entry.provider} / {displayModel(entry.provider, entry.model)}
              </h2>

              {meta?.cwd && (
                <div
                  className="metric-num mt-4 truncate text-[14px] font-medium uppercase leading-none tracking-[0.08em] text-txt-2"
                  title={meta.cwd}
                >
                  {displayCwd(meta.cwd)}
                </div>
              )}
            </div>

            <span className="metric-num shrink-0 whitespace-nowrap pt-1 text-[14px] font-semibold uppercase leading-none tracking-[0.08em] text-txt tabular-nums">
              {dateStr} &middot; {timeStr}
            </span>
          </div>

          {headerTelemetry.length > 0 && (
            <>
              <div className="mt-5 h-px bg-edge" />
              <div className="mt-5 flex flex-wrap items-center gap-3">
                {headerTelemetry.map((chip) => (
                  <span
                    key={chip.text}
                    className={`metric-num border border-edge-strong bg-raised/70 px-4 py-2 text-[14px] font-semibold uppercase leading-none tracking-[0.08em] ${
                      chip.tone ?? "text-txt-2"
                    }`}
                  >
                    {chip.text}
                  </span>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
      <div className="hairline-x" />

      {/* Tab bar — pressed-key switch bank reading as the second deck of
          the instrument panel the header above established. Each cell now
          carries a label-over-readout pair mirroring the header's cell
          rhythm (CAPTURED / Apr 14 · 10:08:55, INSPECT / 5 messages). The
          readout doubles as a glance-signal: REQUEST's token count tells
          you how heavy the captured call was, RESPONSE's em-dash tells you
          the channel is empty without needing the click.
          The EDITED marker rides the right filler: it's metadata, not an
          alert, so it belongs alongside navigation. */}
      <div className="flex border-y border-edge">
        {(["inspect", "request", "response", "transport"] as const).map((t) => {
          const disabled =
            (t === "response" && detail.response_ir == null) ||
            (t === "transport" && detail.transport == null);
          const active = tab === t;
          const readout = tabReadout(t, detail);
          const label = t === "inspect" ? inspectLabel : t;
          return (
            <button
              key={t}
              type="button"
              onClick={() => !disabled && setTab(t)}
              disabled={disabled}
              className={`group relative cursor-pointer px-6 py-2 text-left transition-all duration-150 ${
                active ? "tab-pressed" : disabled ? "tab-rest cursor-not-allowed" : "tab-rest"
              }`}
            >
              <div className="flex flex-col gap-1.5">
                <span
                  className={`text-[12px] font-medium uppercase tracking-[0.14em] leading-none transition-colors duration-150 ${
                    active
                      ? "text-txt"
                      : disabled
                        ? "text-txt-3/40"
                        : "text-txt-3 group-hover:text-txt-2"
                  }`}
                >
                  {label}
                </span>
                {/* Non-breaking space when readout is null so the row
                    keeps its double-line height and the tabs don't twitch
                    between 1- and 2-line layouts as data arrives. */}
                <span
                  className={`text-[11px] metric-num leading-none transition-colors duration-150 ${
                    active ? "text-txt-2" : disabled ? "text-txt-3/30" : "text-txt-3"
                  }`}
                >
                  {readout ?? "\u00A0"}
                </span>
              </div>
            </button>
          );
        })}
        <div className="flex-1 tab-rest flex items-center justify-end pr-6">
          {entry.mutated_manually && (
            <span className="flex items-center gap-1.5 text-[11px] uppercase tracking-[0.18em] text-amber">
              <span className="h-1 w-1 rounded-full bg-amber" />
              Edited
            </span>
          )}
        </div>
      </div>

      {/* Tab content — request tabs default to what was actually sent to
          the provider (curated IR when the pipeline or a breakpoint edit
          mutated the request), falling back to the original IR otherwise. */}
      <div className="flex-1 overflow-y-auto">
        {deferredTab === "inspect" ? (
          <InspectTab
            detail={detail}
            onJumpToTransportFrame={(messageIndex) => {
              startTransition(() => {
                setTransportFocus({ exchangeId: id, messageIndex });
                setTab("transport");
              });
            }}
          />
        ) : deferredTab === "request" ? (
          <JsonView payload={detail.request_curated_ir ?? detail.request_ir} />
        ) : deferredTab === "transport" ? (
          <div className="flex h-full flex-col">
            <TransportDiagnostics diagnostics={detail.transport_diagnostics} />
            {detail.transport_diagnostics.length > 0 && <div className="hairline-x" />}
            <div className="min-h-0 flex-1">
              {detail.transport?.provider === "codex" ? (
                <CodexTransportPanel
                  transport={detail.transport}
                  focusedMessageIndex={
                    transportFocus?.exchangeId === id ? transportFocus.messageIndex : null
                  }
                />
              ) : (
                <JsonView payload={detail.transport} emptyLabel="No transport data" />
              )}
            </div>
          </div>
        ) : (
          <JsonView payload={detail.response_ir} emptyLabel="No response data" />
        )}
      </div>
    </div>
  );
}
