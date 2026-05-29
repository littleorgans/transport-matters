import { formatClockTime, pluralize } from "../../lib/formatting";
import type { CodexSemanticEvent, CodexTurnStatus, CodexTurnSummary } from "../../types";

const STATUS_TONE: Record<CodexTurnStatus, string> = {
  open: "text-amber",
  completed: "text-sage",
  failed: "text-rose",
  interrupted: "text-lavender",
};

const SOURCE_TONE: Record<CodexSemanticEvent["source"], string> = {
  client: "text-sky",
  server: "text-sage",
  proxy: "text-lavender",
  operator: "text-amber",
};

const KIND_LABEL: Record<CodexSemanticEvent["kind"], string> = {
  turn_started: "turn started",
  request_curated: "request curated",
  breakpoint_paused: "breakpoint paused",
  breakpoint_released: "breakpoint released",
  assistant_item_completed: "assistant item completed",
  tool_call_completed: "tool call completed",
  tool_output_submitted: "tool output submitted",
  response_completed: "response completed",
  response_failed: "response failed",
  turn_finalized: "turn finalized",
};

interface CodexTimelineProps {
  events: CodexSemanticEvent[];
  turn: CodexTurnSummary;
  onJumpToTransportFrame?: (messageIndex: number) => void;
}

interface EventCopy {
  summary: string;
  detail: string | null;
}

function formatDuration(startedAt: string, endedAt: string | null): string | null {
  if (endedAt === null) {
    return null;
  }
  const durationMs = new Date(endedAt).getTime() - new Date(startedAt).getTime();
  if (!Number.isFinite(durationMs) || durationMs < 0) {
    return null;
  }
  if (durationMs < 1000) {
    return `${Math.round(durationMs)}ms`;
  }
  const seconds = durationMs / 1000;
  if (seconds < 60) {
    return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60);
  return `${minutes}m ${remainder}s`;
}

function prettifyToken(value: string): string {
  return value.replaceAll("_", " ");
}

function eventCopy(event: CodexSemanticEvent): EventCopy {
  switch (event.kind) {
    case "turn_started":
      return {
        summary: "Client sent response.create to open the turn.",
        detail: null,
      };
    case "request_curated":
      return {
        summary: "Transport Matters applied local request curation before upstream send.",
        detail: null,
      };
    case "breakpoint_paused":
      return {
        summary: "Breakpoint paused the turn before execution continued.",
        detail: event.data.flow_id ? `flow ${event.data.flow_id}` : null,
      };
    case "breakpoint_released":
      return {
        summary: "Breakpoint released the turn back to the websocket session.",
        detail: event.data.flow_id ? `flow ${event.data.flow_id}` : null,
      };
    case "assistant_item_completed":
      return {
        summary: `${prettifyToken(event.data.phase ?? event.data.item_type)} committed as ${
          event.data.role ?? "assistant"
        } output.`,
        detail: [
          pluralize(event.data.text_chars, "char"),
          event.data.item_id ? `item ${event.data.item_id}` : null,
        ]
          .filter(Boolean)
          .join(" · "),
      };
    case "tool_call_completed":
      return {
        summary: `${event.data.tool_name ?? "tool call"} completed upstream.`,
        detail: [
          pluralize(event.data.arguments_chars, "arg char", "arg chars"),
          event.data.call_id ? `call ${event.data.call_id}` : null,
          event.data.item_id ? `item ${event.data.item_id}` : null,
        ]
          .filter(Boolean)
          .join(" · "),
      };
    case "tool_output_submitted":
      return {
        summary: "Client submitted tool output for the next step of the turn.",
        detail: [
          `input ${event.data.input_index}`,
          pluralize(event.data.output_chars, "char"),
          event.data.call_id ? `call ${event.data.call_id}` : null,
        ]
          .filter(Boolean)
          .join(" · "),
      };
    case "response_completed":
      return {
        summary: "Server marked the response completed.",
        detail: [
          event.data.stop_reason,
          event.data.response_status ? `status ${event.data.response_status}` : null,
          event.data.response_id ? `response ${event.data.response_id}` : null,
        ]
          .filter(Boolean)
          .join(" · "),
      };
    case "response_failed":
      return {
        summary: "Server marked the response failed.",
        detail: [
          event.data.stop_reason,
          event.data.response_status ? `status ${event.data.response_status}` : null,
          event.data.response_id ? `response ${event.data.response_id}` : null,
        ]
          .filter(Boolean)
          .join(" · "),
      };
    case "turn_finalized":
      return {
        summary: `Turn finalized as ${event.data.status}.`,
        detail: [
          event.data.stop_reason,
          prettifyToken(event.data.terminal_cause),
          pluralize(event.data.text_chars, "char"),
          pluralize(event.data.tool_calls, "tool call"),
          event.data.close_code != null ? `close ${event.data.close_code}` : null,
        ]
          .filter(Boolean)
          .join(" · "),
      };
  }
}

function openTurnCopy(turn: CodexTurnSummary): string | null {
  if (turn.status !== "open" || turn.cursor === null) {
    return null;
  }
  const assistantItems = Object.keys(turn.cursor.open_assistant_items).length;
  const toolCalls = Object.keys(turn.cursor.open_tool_calls).length;
  return [
    `next frame ${turn.cursor.next_message_index}`,
    pluralize(assistantItems, "open assistant item"),
    pluralize(toolCalls, "open tool call"),
  ].join(" · ");
}

function EventRow({
  event,
  onJumpToTransportFrame,
}: {
  event: CodexSemanticEvent;
  onJumpToTransportFrame?: (messageIndex: number) => void;
}) {
  const copy = eventCopy(event);
  const jumpTarget = event.transport_ref?.message_index ?? null;

  return (
    <div className="px-5 py-4">
      <div className="flex items-start gap-4">
        <div className="w-24 shrink-0">
          <div className="metric-num text-[12px] text-txt-3">
            #{event.seq.toString().padStart(3, "0")}
          </div>
          <div className="label mt-1 tabular-nums normal-case tracking-[0.12em]">
            {formatClockTime(event.ts)}
          </div>
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`chip ${SOURCE_TONE[event.source]}`}>{event.source}</span>
            <span className="label text-txt-2">{KIND_LABEL[event.kind]}</span>
          </div>
          <p className="mt-2 text-[13px] leading-5 text-txt">{copy.summary}</p>
          {copy.detail && <p className="mt-1 text-[12px] leading-5 text-txt-2">{copy.detail}</p>}
        </div>

        {jumpTarget !== null && onJumpToTransportFrame ? (
          <button
            type="button"
            onClick={() => onJumpToTransportFrame(jumpTarget)}
            className="shrink-0 cursor-pointer border border-edge bg-canvas px-3 py-1.5 text-[11px] uppercase tracking-[0.14em] text-txt-2 transition-colors hover:border-edge-strong hover:text-txt"
            aria-label={`Jump to transport frame ${jumpTarget}`}
          >
            frame {jumpTarget}
          </button>
        ) : (
          <span className="label shrink-0 text-txt-3">local</span>
        )}
      </div>
    </div>
  );
}

export function CodexTimeline({ events, turn, onJumpToTransportFrame }: CodexTimelineProps) {
  const duration = formatDuration(turn.started_at, turn.ended_at);
  const openTurnDetail = openTurnCopy(turn);

  return (
    <section className="card top-highlight">
      <div className="px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className={`chip ${STATUS_TONE[turn.status]}`}>{turn.status}</span>
              <span className="label text-txt-2">turn {turn.turn_index}</span>
              {turn.stop_reason && <span className="label text-txt-3">{turn.stop_reason}</span>}
            </div>
            <div className="mt-3 flex flex-wrap items-baseline gap-x-5 gap-y-2 text-[12px] text-txt-2">
              <span className="metric-num">
                frames {turn.message_range_start}→{turn.message_range_end}
              </span>
              <span className="metric-num">{pluralize(turn.text_chars, "char")}</span>
              <span className="metric-num">{pluralize(turn.tool_calls, "tool call")}</span>
              {duration && <span className="metric-num">{duration}</span>}
              {turn.terminal_cause && (
                <span className="label text-txt-3">{prettifyToken(turn.terminal_cause)}</span>
              )}
            </div>
          </div>

          {openTurnDetail && (
            <div className="max-w-xs rounded-md border border-amber/25 bg-amber/6 px-4 py-3">
              <div className="label text-amber">live state</div>
              <p className="mt-2 text-[12px] leading-5 text-txt-2">{openTurnDetail}</p>
            </div>
          )}
        </div>
      </div>

      <div className="hairline-x" />

      {events.length > 0 ? (
        <div>
          {events.map((event, index) => (
            <div key={event.event_id}>
              <EventRow event={event} onJumpToTransportFrame={onJumpToTransportFrame} />
              {index < events.length - 1 && <div className="hairline-x mx-5" />}
            </div>
          ))}
        </div>
      ) : (
        <div className="px-5 py-8 text-center">
          <span className="label">No committed semantic events</span>
        </div>
      )}
    </section>
  );
}
