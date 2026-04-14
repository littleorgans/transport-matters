import { useQuery } from "@tanstack/react-query";
import { useDeferredValue, useEffect, useState } from "react";
import { fetchExchange } from "../api";
import { displayModel } from "../lib/formatting";
import { useUIStore } from "../stores/uiStore";
import type { ExchangeDetail as ExchangeDetailPayload } from "../types";
import { InspectTab } from "./detail/InspectTab";
import { JsonView } from "./detail/JsonView";

interface ExchangeDetailProps {
  id: string;
}

type DetailTab = "inspect" | "request" | "response";

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
  const { entry, response_ir } = detail;

  if (t === "inspect") {
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

  // response — em dash when there's no payload, so the dimmed tab reads
  // as "no channel here" instead of ambiguously empty.
  if (!response_ir || !entry.res) return "\u2014";
  const out = entry.res.output_tokens ?? 0;
  return out > 0 ? `${out.toLocaleString()} tokens` : "\u2014";
}

export function ExchangeDetail({ id }: ExchangeDetailProps) {
  const [tab, setTab] = useState<DetailTab>("inspect");
  const deferredTab = useDeferredValue(tab);

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
      {/* Header — archived-exchange instrument strip, true sibling of
          PausedHeader. Same stretched column rhythm, same label-above-
          value stacking, same divider weight. What swaps is the hero:
          where PausedHeader leads with a live amber Elapsed counter,
          this one leads with a preserved Captured timestamp in bone-
          neutral tones. The absence of the amber caution cell is the
          archival signal — nothing is ticking, nothing is blocking. */}
      <div className="top-highlight bg-surface">
        <div className="flex items-stretch">
          {/* Captured — archival hero readout. Date leads in txt
              weight, a whisper-thin middle dot separates, time trails
              in muted txt-2. JetBrains tabular figures keep the glyphs
              on-grid so it reads as instrument typography. */}
          <div className="flex shrink-0 flex-col justify-center gap-1 border-r border-edge px-6 py-2">
            <span className="label">Captured</span>
            <span className="metric-num text-[13px] leading-none tabular-nums whitespace-nowrap">
              <span className="text-txt">{dateStr}</span>
              <span className="mx-2 text-txt-3">&middot;</span>
              <span className="text-txt-2">{timeStr}</span>
            </span>
          </div>

          {/* Provider / model — stretches to fill so FLOW can anchor at
              the right bookend. Provider rides the micro-label slot,
              model sits as the hero value below. Mirrors PausedHeader's
              combined cell so the archived and live views share one
              rhythm; the only swap is the hero over on the left. */}
          <div className="flex min-w-0 flex-1 flex-col justify-center gap-1 px-6 py-2">
            <span className="label truncate">{entry.provider}</span>
            <h2 className="metric-num text-[13px] leading-none text-txt truncate">
              {displayModel(entry.provider, entry.model)}
            </h2>
          </div>

          {/* Flow id — right-anchored end-cap mirroring PausedHeader's
              FLOW bookend. Content right-aligned so label and id hug the
              outer edge; first eight chars match how the paused view
              abbreviates the same identifier. */}
          <div className="flex shrink-0 flex-col items-end justify-center gap-1 px-6 py-2">
            <span className="label">Flow</span>
            <span className="metric-num text-[13px] leading-none text-txt-2 whitespace-nowrap">
              {entry.id.slice(0, 8)}
            </span>
          </div>
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
        {(["inspect", "request", "response"] as const).map((t) => {
          const disabled = t === "response" && detail.response_ir == null;
          const active = tab === t;
          const readout = tabReadout(t, detail);
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
                  {t}
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
          <InspectTab detail={detail} />
        ) : deferredTab === "request" ? (
          <JsonView payload={detail.request_curated_ir ?? detail.request_ir} />
        ) : (
          <JsonView payload={detail.response_ir} emptyLabel="No response data" />
        )}
      </div>
    </div>
  );
}
