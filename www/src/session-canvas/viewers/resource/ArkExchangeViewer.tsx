/**
 * Canvas-owned, read-only exchange viewer (the Ark fork of the inspector's
 * ExchangeDetail — locked decision: canvas forks its own Ark exchange viewer).
 *
 * Renders the same exchange content the inspector detail shows for a
 * provider-exchange pane — header identity, four tabs with readouts, and the
 * per-tab payloads — with Ark tabs and vanilla BEM canvas-* CSS. The inspect
 * fullscreen stays (the desktop Escape order — palette, dock, fullscreen —
 * depends on it). Deliberately omitted: editor sections, breakpoint/override
 * affordances, export, the "Edited" marker, and every store import.
 */

import { Tabs } from "@ark-ui/react/tabs";
import { useQuery } from "@tanstack/react-query";
import { type ReactElement, useState } from "react";
import { fetchExchange } from "../../../api";
import { useFullscreen } from "../../../hooks/useFullscreen";
import { useMeta } from "../../../hooks/useMeta";
import { displayCwd, displayModel, formatClockTime } from "../../../lib/formatting";
import { exchangeKey } from "../../../lib/queryKeys";
import type { ExchangeDetail } from "../../../types";
import {
  ExchangeInspectPanel,
  ExchangeJsonPanel,
  ExchangeTransportPanel,
} from "./ArkExchangePanels";
import "./exchange-viewer.css";

export type ExchangeDetailTab = "inspect" | "request" | "response" | "transport";

const DETAIL_TABS: readonly ExchangeDetailTab[] = ["inspect", "request", "response", "transport"];

/** Map the backend's initialView onto a detail tab. */
export function toDetailTab(view: string | null | undefined): ExchangeDetailTab {
  switch (view) {
    case "request":
      return "request";
    case "response":
      return "response";
    case "diagnostics":
      return "transport";
    default:
      // "events" and null fall back to the inspect/timeline tab.
      return "inspect";
  }
}

function hasCodexTimeline(detail: ExchangeDetail): boolean {
  return detail.entry.provider === "codex" && detail.events != null && detail.turn != null;
}

interface TelemetryChip {
  text: string;
  tone?: "sage" | "rose" | "lavender" | "amber" | "sky";
}

function codexTurnTone(
  status: NonNullable<ExchangeDetail["turn"]>["status"],
): TelemetryChip["tone"] {
  if (status === "completed") return "sage";
  if (status === "failed") return "rose";
  if (status === "interrupted") return "lavender";
  return "amber";
}

function codexHeaderTelemetry(detail: ExchangeDetail): TelemetryChip[] {
  if (detail.turn == null) return [];
  const transportUnit = detail.transport?.protocol === "http" ? "events" : "frames";
  const chips: TelemetryChip[] = [
    {
      text: `turn ${detail.turn.turn_index} ${detail.turn.status}`,
      tone: codexTurnTone(detail.turn.status),
    },
    {
      text: `${transportUnit} ${detail.turn.message_range_start} to ${detail.turn.message_range_end}`,
    },
    { text: `${detail.turn.text_chars.toLocaleString()} chars`, tone: "sky" },
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
 * Per-tab readout: a contextual metric under each tab label. Unit choices
 * follow the tokens-vs-chars rule — real tokens when the payload has them,
 * raw chars otherwise, no heuristic conversion. Null means "render nothing"
 * so the readout line stays absent instead of fake-empty.
 */
function tabReadout(tab: ExchangeDetailTab, detail: ExchangeDetail): string | null {
  const { entry, response_ir, transport } = detail;

  if (tab === "inspect") {
    if (hasCodexTimeline(detail)) {
      const eventCount = detail.events?.length ?? 0;
      const status = detail.turn?.status === "open" ? "live" : detail.turn?.status;
      return status
        ? `${eventCount.toLocaleString()} events · ${status}`
        : `${eventCount.toLocaleString()} events`;
    }
    const count = entry.req?.messages_count ?? 0;
    if (!count) return null;
    return `${count.toLocaleString()} ${count === 1 ? "message" : "messages"}`;
  }

  if (tab === "request") {
    if (entry.res) {
      const contextTokens =
        (entry.res.input_tokens ?? 0) +
        (entry.res.cache_creation_input_tokens ?? 0) +
        (entry.res.cache_read_input_tokens ?? 0);
      if (contextTokens > 0) return `${contextTokens.toLocaleString()} tokens`;
    }
    const chars = entry.req?.total_chars ?? 0;
    return chars > 0 ? `${chars.toLocaleString()} chars` : null;
  }

  if (tab === "transport") {
    const messageCount = transport?.messages.length ?? 0;
    if (messageCount === 0) return null;
    const unit = transport?.protocol === "http" ? "event" : "frame";
    return `${messageCount.toLocaleString()} ${messageCount === 1 ? unit : `${unit}s`}`;
  }

  // response — em dash when there's no payload, so the dimmed tab reads as
  // "no channel here" instead of ambiguously empty.
  if (!response_ir || !entry.res) return "—";
  const out = entry.res.output_tokens ?? 0;
  return out > 0 ? `${out.toLocaleString()} tokens` : "—";
}

export function ArkExchangeViewer({
  runId,
  exchangeId,
  initialView,
}: {
  runId: string;
  exchangeId: string;
  initialView?: string | null;
}): ReactElement {
  const {
    data: detail,
    isLoading,
    error,
  } = useQuery({
    queryKey: exchangeKey(runId, exchangeId),
    queryFn: () => fetchExchange(runId, exchangeId),
    retry: false,
  });

  if (isLoading) {
    return <div aria-busy="true" className="canvas-exchange canvas-exchange--center" />;
  }

  if (error) {
    return (
      <div className="canvas-exchange canvas-exchange--center" role="alert">
        <p className="canvas-exchange__error">
          {error instanceof Error ? error.message : "Failed to load exchange"}
        </p>
      </div>
    );
  }

  if (!detail) {
    return <div className="canvas-exchange canvas-exchange--center" />;
  }

  return <ExchangeBody detail={detail} initialTab={toDetailTab(initialView)} />;
}

function isTabDisabled(tab: ExchangeDetailTab, detail: ExchangeDetail): boolean {
  if (tab === "response") return detail.response_ir == null;
  if (tab === "transport") return detail.transport == null;
  return false;
}

function ExchangeBody({
  detail,
  initialTab,
}: {
  detail: ExchangeDetail;
  initialTab: ExchangeDetailTab;
}): ReactElement {
  // A launch view can point at a channel this exchange does not carry
  // (e.g. "response" before the response landed); fall back to inspect.
  const [activeTab, setActiveTab] = useState<ExchangeDetailTab>(() =>
    isTabDisabled(initialTab, detail) ? "inspect" : initialTab,
  );
  const { isFullscreen, openFullscreen, closeFullscreen } = useFullscreen();

  return (
    <div className="canvas-exchange">
      <ExchangeHeader detail={detail} />
      <Tabs.Root
        className="canvas-exchange__tabs"
        onValueChange={(details) => setActiveTab(details.value as ExchangeDetailTab)}
        value={activeTab}
      >
        <Tabs.List className="canvas-exchange__tab-list">
          {DETAIL_TABS.map((tab) => {
            const readout = tabReadout(tab, detail);
            const label = tab === "inspect" && hasCodexTimeline(detail) ? "timeline" : tab;
            return (
              <Tabs.Trigger
                className="canvas-exchange__tab"
                disabled={isTabDisabled(tab, detail)}
                key={tab}
                value={tab}
              >
                <span className="canvas-exchange__tab-label">{label}</span>
                <span className="canvas-exchange__tab-readout">{readout ?? " "}</span>
              </Tabs.Trigger>
            );
          })}
          {activeTab === "inspect" && (
            <div className="canvas-exchange__tab-actions">
              <button
                aria-label="Open inspect fullscreen"
                className="canvas-button canvas-exchange__fullscreen-toggle"
                onClick={openFullscreen}
                type="button"
              >
                <svg
                  aria-hidden="true"
                  className="canvas-exchange__fullscreen-icon"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <path
                    d="M14 4h6v6M20 4l-7 7M10 20H4v-6M4 20l7-7"
                    stroke="currentColor"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth="1.5"
                  />
                </svg>
              </button>
            </div>
          )}
        </Tabs.List>
        <Tabs.Content className="canvas-exchange__panel" value="inspect">
          <ExchangeInspectPanel detail={detail} />
        </Tabs.Content>
        <Tabs.Content className="canvas-exchange__panel" value="request">
          <ExchangeJsonPanel
            emptyLabel="No request data"
            value={detail.request_curated_ir ?? detail.request_ir}
          />
        </Tabs.Content>
        <Tabs.Content className="canvas-exchange__panel" value="response">
          <ExchangeJsonPanel emptyLabel="No response data" value={detail.response_ir} />
        </Tabs.Content>
        <Tabs.Content className="canvas-exchange__panel" value="transport">
          <ExchangeTransportPanel detail={detail} />
        </Tabs.Content>
      </Tabs.Root>
      {isFullscreen && (
        <div className="canvas-exchange__fullscreen">
          <button
            aria-label="Close inspect fullscreen"
            className="canvas-button canvas-exchange__fullscreen-close"
            onClick={closeFullscreen}
            type="button"
          >
            {"×"}
          </button>
          <div className="canvas-exchange__fullscreen-body">
            <ExchangeInspectPanel detail={detail} />
          </div>
        </div>
      )}
    </div>
  );
}

function ExchangeHeader({ detail }: { detail: ExchangeDetail }): ReactElement {
  const { meta } = useMeta();
  const { entry } = detail;
  const isWaiting = !entry.codex_turn && entry.res === null;
  const telemetry = codexHeaderTelemetry(detail);
  const ts = new Date(entry.ts);
  const dateStr = ts.toLocaleDateString("en-US", { month: "short", day: "numeric" });

  return (
    <header className="canvas-exchange__header">
      <div className="canvas-exchange__identity">
        <h2 className="canvas-exchange__title">
          {entry.provider} / {displayModel(entry.provider, entry.model)}
        </h2>
        <span className="canvas-exchange__timestamp">
          {dateStr} · {formatClockTime(ts)}
        </span>
      </div>
      {meta?.cwd && (
        <div className="canvas-exchange__cwd" title={meta.cwd}>
          {displayCwd(meta.cwd)}
        </div>
      )}
      {(isWaiting || telemetry.length > 0) && (
        <div className="canvas-exchange__chips">
          {isWaiting && (
            <span className="canvas-exchange__chip" data-tone="amber">
              awaiting response
            </span>
          )}
          {telemetry.map((chip) => (
            <span className="canvas-exchange__chip" data-tone={chip.tone} key={chip.text}>
              {chip.text}
            </span>
          ))}
        </div>
      )}
    </header>
  );
}
