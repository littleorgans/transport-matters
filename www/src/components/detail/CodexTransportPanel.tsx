import { type MutableRefObject, useEffect, useRef } from "react";
import type {
  TransportArtifacts,
  TransportHeader,
  TransportHttpArtifacts,
  TransportMessageArtifact,
} from "../../types";
import { JsonView } from "./JsonView";

interface CodexTransportPanelProps {
  transport: TransportArtifacts;
  focusedMessageIndex: number | null;
}

interface MessageRow {
  index: number;
  label: string;
  message: TransportMessageArtifact;
}

const CODEX_HTTP_HEADER_NAMES = new Set(["session-id", "thread-id", "x-codex-turn-metadata"]);

function formatTimestamp(ts: string | null | undefined): string | null {
  if (!ts) {
    return null;
  }
  const parsed = new Date(ts);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  return parsed.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function endpointUrl(parts: { scheme: string; host: string; path: string }): string {
  return `${parts.scheme}://${parts.host}${parts.path}`;
}

function transportEndpoint(transport: TransportArtifacts): string {
  if (transport.protocol === "websocket") {
    return endpointUrl(transport.upgrade);
  }
  if (transport.request === null) {
    return "HTTP request metadata unavailable";
  }
  return `${transport.request.method ?? "HTTP"} ${endpointUrl(transport.request)}`;
}

function statusCode(transport: TransportArtifacts): number | null {
  if (transport.protocol === "websocket") {
    return transport.upgrade.response_status_code;
  }
  return transport.response?.status_code ?? null;
}

function payloadLabel(
  protocol: TransportArtifacts["protocol"],
  message: TransportMessageArtifact,
): string {
  if (message.event_type) {
    return message.event_type;
  }
  if (protocol === "http") {
    return message.direction === "server" ? "SSE payload" : "request payload";
  }
  return message.is_text ? "text frame" : "binary frame";
}

function payloadPreview(message: TransportMessageArtifact): string {
  if (message.dropped) {
    return "Payload was dropped during capture.";
  }
  if (message.payload_text) {
    const compact = message.payload_text.replace(/\s+/g, " ").trim();
    if (compact.length <= 220) {
      return compact;
    }
    return `${compact.slice(0, 220)}...`;
  }
  if (message.payload_json) {
    const compact = JSON.stringify(message.payload_json);
    if (compact.length <= 220) {
      return compact;
    }
    return `${compact.slice(0, 220)}...`;
  }
  if (message.payload_base64) {
    return `Base64 payload, ${message.payload_base64.length.toLocaleString()} chars.`;
  }
  return "No payload body captured.";
}

function messageKey(index: number, message: TransportMessageArtifact): string {
  const payloadIdentity =
    message.payload_text ??
    (message.payload_json ? JSON.stringify(message.payload_json) : null) ??
    message.payload_base64 ??
    "empty";
  return [
    index.toString(),
    message.ts ?? "no-ts",
    message.direction,
    message.event_type ?? "no-type",
    message.size_bytes.toString(),
    payloadIdentity,
  ].join("|");
}

function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return `${count.toLocaleString()} ${count === 1 ? singular : plural}`;
}

function httpSseEventCount(transport: TransportHttpArtifacts): number {
  return transport.messages.filter((message) => message.direction === "server").length;
}

function codexHttpHeaders(transport: TransportHttpArtifacts): TransportHeader[] {
  return (transport.request?.headers ?? []).filter((header) =>
    CODEX_HTTP_HEADER_NAMES.has(header.name.toLowerCase()),
  );
}

function transportRows(transport: TransportArtifacts): MessageRow[] {
  let sseIndex = 0;
  return transport.messages.map((message, index) => {
    if (transport.protocol === "websocket") {
      return { index, label: `frame ${index}`, message };
    }
    if (message.direction === "server") {
      sseIndex += 1;
      return { index, label: `SSE event ${sseIndex}`, message };
    }
    return { index, label: "request body", message };
  });
}

function HttpProvenance({ transport }: { transport: TransportHttpArtifacts }) {
  const requestHeaders = transport.request?.headers.length ?? 0;
  const responseHeaders = transport.response?.headers.length ?? 0;
  const identityHeaders = codexHttpHeaders(transport);

  return (
    <div className="mt-4 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="label text-txt-3">{pluralize(requestHeaders, "request header")}</span>
        <span className="label text-txt-3">{pluralize(responseHeaders, "response header")}</span>
        <span className="label text-txt-3">
          {pluralize(httpSseEventCount(transport), "SSE event")}
        </span>
      </div>
      {identityHeaders.length > 0 && (
        <div className="space-y-1">
          {identityHeaders.map((header) => (
            <div
              key={`${header.name}:${header.value}`}
              className="grid min-w-0 grid-cols-[10rem_minmax(0,1fr)] gap-3 text-[12px] leading-5"
            >
              <span className="label truncate text-txt-3 normal-case tracking-[0.12em]">
                {header.name}
              </span>
              <span className="min-w-0 break-all font-mono text-txt-2">{header.value}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function TransportOverview({ transport }: { transport: TransportArtifacts }) {
  const status = statusCode(transport);

  return (
    <div className="px-8 py-5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="chip text-sky">transport</span>
        <span className="chip text-txt-2">{transport.protocol}</span>
        <span className="metric-num text-[12px] text-txt-2">{transportEndpoint(transport)}</span>
        {status !== null && <span className="label text-txt-3">status {status}</span>}
        {transport.protocol === "websocket" &&
          transport.close !== null &&
          transport.close.close_code !== null && (
            <span className="label text-txt-3">close {transport.close.close_code}</span>
          )}
      </div>
      {transport.protocol === "http" && <HttpProvenance transport={transport} />}
    </div>
  );
}

function MissingTransportMessage({
  protocol,
  focusedMessageIndex,
}: {
  protocol: TransportArtifacts["protocol"];
  focusedMessageIndex: number;
}) {
  const noun = protocol === "http" ? "Message" : "Frame";
  return (
    <div className="mx-8 mb-5 rounded-md border border-amber/25 bg-amber/6 px-4 py-3">
      <p className="text-[12px] leading-5 text-txt-2">
        {noun} {focusedMessageIndex} is referenced by the semantic timeline but is not present in
        the stored transport capture.
      </p>
    </div>
  );
}

function TransportMessageList({
  transport,
  focusedMessageIndex,
  messageRefs,
}: {
  transport: TransportArtifacts;
  focusedMessageIndex: number | null;
  messageRefs: MutableRefObject<Record<number, HTMLDivElement | null>>;
}) {
  const rows = transportRows(transport);
  if (rows.length === 0) {
    return (
      <div className="flex items-center justify-center px-8 py-12">
        <span className="label">
          {transport.protocol === "http"
            ? "No HTTP events captured"
            : "No websocket frames captured"}
        </span>
      </div>
    );
  }

  return (
    <div>
      {rows.map(({ index, label, message }) => {
        const isFocused = focusedMessageIndex === index;
        const timeLabel = formatTimestamp(message.ts);
        return (
          <div
            key={messageKey(index, message)}
            ref={(node) => {
              messageRefs.current[index] = node;
            }}
            className={`px-8 py-4 transition-colors ${
              isFocused ? "bg-sky/6" : "hover:bg-raised/40"
            }`}
            data-transport-message-index={index}
          >
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={`chip ${message.direction === "client" ? "text-sky" : "text-sage"}`}
                  >
                    {message.direction}
                  </span>
                  <span className="metric-num text-[12px] text-txt-2">{label}</span>
                  <span className="label text-txt-3 normal-case tracking-[0.12em]">
                    {payloadLabel(transport.protocol, message)}
                  </span>
                  {message.dropped && <span className="label text-rose">dropped</span>}
                </div>
                <p className="mt-2 break-words font-mono text-[12px] leading-5 text-txt-2">
                  {payloadPreview(message)}
                </p>
              </div>

              <div className="shrink-0 text-right">
                {timeLabel && (
                  <div className="metric-num text-[12px] text-txt-2 tabular-nums">{timeLabel}</div>
                )}
                <div className="label mt-1 text-txt-3">
                  {message.size_bytes.toLocaleString()} bytes
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function CodexTransportPanel({ transport, focusedMessageIndex }: CodexTransportPanelProps) {
  const messageRefs = useRef<Record<number, HTMLDivElement | null>>({});

  useEffect(() => {
    if (focusedMessageIndex === null) {
      return;
    }
    const target = messageRefs.current[focusedMessageIndex];
    if (!target || typeof target.scrollIntoView !== "function") {
      return;
    }
    target.scrollIntoView({
      block: "center",
      behavior: "smooth",
    });
  }, [focusedMessageIndex]);

  const focusedMessageMissing =
    focusedMessageIndex !== null && transport.messages[focusedMessageIndex] == null;

  return (
    <div className="flex h-full flex-col">
      <TransportOverview transport={transport} />
      {focusedMessageMissing && (
        <MissingTransportMessage
          protocol={transport.protocol}
          focusedMessageIndex={focusedMessageIndex}
        />
      )}

      <div className="hairline-x" />

      <div className="min-h-0 flex-1 overflow-y-auto">
        <TransportMessageList
          transport={transport}
          focusedMessageIndex={focusedMessageIndex}
          messageRefs={messageRefs}
        />

        <details className="border-t border-edge">
          <summary className="cursor-pointer px-8 py-3 text-[12px] uppercase tracking-[0.16em] text-txt-3 transition-colors hover:text-txt-2">
            Raw transport JSON
          </summary>
          <div className="h-[28rem] border-t border-edge">
            <JsonView payload={transport} />
          </div>
        </details>
      </div>
    </div>
  );
}
