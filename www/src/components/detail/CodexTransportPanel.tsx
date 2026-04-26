import { useEffect, useRef } from "react";
import type { TransportArtifacts, TransportMessageArtifact } from "../../types";
import { JsonView } from "./JsonView";

interface CodexTransportPanelProps {
  transport: TransportArtifacts;
  focusedMessageIndex: number | null;
}

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

function frameLabel(message: TransportMessageArtifact): string {
  if (message.event_type) {
    return message.event_type;
  }
  return message.is_text ? "text frame" : "binary frame";
}

function framePreview(message: TransportMessageArtifact): string {
  if (message.dropped) {
    return "Frame payload was dropped during capture.";
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

function frameKey(index: number, message: TransportMessageArtifact): string {
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

export function CodexTransportPanel({ transport, focusedMessageIndex }: CodexTransportPanelProps) {
  const frameRefs = useRef<Record<number, HTMLDivElement | null>>({});

  useEffect(() => {
    if (focusedMessageIndex === null) {
      return;
    }
    const target = frameRefs.current[focusedMessageIndex];
    if (!target || typeof target.scrollIntoView !== "function") {
      return;
    }
    target.scrollIntoView({
      block: "center",
      behavior: "smooth",
    });
  }, [focusedMessageIndex]);

  const focusedFrameMissing =
    focusedMessageIndex !== null && transport.messages[focusedMessageIndex] == null;

  return (
    <div className="flex h-full flex-col">
      <div className="px-8 py-5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="chip text-sky">transport</span>
          <span className="metric-num text-[12px] text-txt-2">
            {transport.upgrade.scheme}://{transport.upgrade.host}
            {transport.upgrade.path}
          </span>
          {transport.upgrade.response_status_code !== null && (
            <span className="label text-txt-3">
              status {transport.upgrade.response_status_code}
            </span>
          )}
          {transport.close !== null && transport.close.close_code !== null && (
            <span className="label text-txt-3">close {transport.close.close_code}</span>
          )}
        </div>

        {focusedFrameMissing && (
          <div className="mt-4 rounded-md border border-amber/25 bg-amber/6 px-4 py-3">
            <p className="text-[12px] leading-5 text-txt-2">
              Frame {focusedMessageIndex} is referenced by the semantic timeline but is not present
              in the stored transport capture.
            </p>
          </div>
        )}
      </div>

      <div className="hairline-x" />

      <div className="min-h-0 flex-1 overflow-y-auto">
        {transport.messages.length > 0 ? (
          <div>
            {transport.messages.map((message, index) => {
              const isFocused = focusedMessageIndex === index;
              const timeLabel = formatTimestamp(message.ts);
              return (
                <div
                  key={frameKey(index, message)}
                  ref={(node) => {
                    frameRefs.current[index] = node;
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
                        <span className="metric-num text-[12px] text-txt-2">frame {index}</span>
                        <span className="label text-txt-3 normal-case tracking-[0.12em]">
                          {frameLabel(message)}
                        </span>
                        {message.dropped && <span className="label text-rose">dropped</span>}
                      </div>
                      <p className="mt-2 break-words font-mono text-[12px] leading-5 text-txt-2">
                        {framePreview(message)}
                      </p>
                    </div>

                    <div className="shrink-0 text-right">
                      {timeLabel && (
                        <div className="metric-num text-[12px] text-txt-2 tabular-nums">
                          {timeLabel}
                        </div>
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
        ) : (
          <div className="flex items-center justify-center px-8 py-12">
            <span className="label">No websocket frames captured</span>
          </div>
        )}

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
