/**
 * Tab panels for the canvas-owned exchange viewer. Read-only forks of the
 * inspector detail content: same payload fields, canvas presentation. No
 * editor sections, no breakpoint or override machinery, no store imports.
 */

import type { ReactElement } from "react";
import { blockKey } from "../../../lib/contentBlocks";
import type {
  CodexSemanticEvent,
  ContentBlock,
  ExchangeDetail,
  InternalRequest,
  InternalResponse,
  Message,
  SystemPart,
  ToolDef,
  TransportDiagnostic,
} from "../../../types";
import { TranscriptBlock } from "../transcript-chat/TranscriptMessage";
import { CopyButton } from "./primitives/CopyButton";
import { JsonTree } from "./primitives/JsonTree";

/** JSON payload panel (request / response / transport bodies). */
export function ExchangeJsonPanel({
  emptyLabel,
  value,
}: {
  emptyLabel: string;
  value: object | null;
}): ReactElement {
  if (value === null) {
    return <p className="canvas-exchange__empty">{emptyLabel}</p>;
  }
  return (
    <div className="canvas-exchange__json">
      <div className="canvas-exchange__json-toolbar">
        <CopyButton label="Copy" value={JSON.stringify(value, null, 2)} />
      </div>
      <JsonTree value={value} />
    </div>
  );
}

/**
 * Inspect panel: the request/response content the inspector's inspect tab
 * shows — codex timeline, system parts, request messages, response blocks,
 * and tool definitions — rendered with the canvas block primitives.
 */
export function ExchangeInspectPanel({ detail }: { detail: ExchangeDetail }): ReactElement {
  const originalRequest = detail.request_ir as unknown as InternalRequest | undefined;
  const curatedRequest = detail.request_curated_ir as unknown as InternalRequest | undefined;
  // Original first so pre-mutation entries still appear; curated is the
  // fallback for passthrough rows where request_ir is the only payload.
  const baseRequest = originalRequest ?? curatedRequest;
  const systemParts: SystemPart[] = baseRequest?.system ?? [];
  const messages: Message[] = baseRequest?.messages ?? [];
  const tools: ToolDef[] = baseRequest?.tools ?? [];
  const responseContent: ContentBlock[] =
    (detail.response_ir as InternalResponse | null)?.content ?? [];
  const showsCodexTimeline =
    detail.entry.provider === "codex" && detail.events != null && detail.turn != null;

  return (
    <div className="canvas-exchange__inspect">
      {showsCodexTimeline && detail.events != null && (
        <ExchangeSection title="timeline">
          <ol className="canvas-exchange__events">
            {detail.events.map((event) => (
              <CodexEventRow event={event} key={event.event_id} />
            ))}
          </ol>
        </ExchangeSection>
      )}

      {systemParts.length > 0 && (
        <ExchangeSection title="system">
          {systemParts.map((part, index) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: fetched payload snapshot, never reordered
            <TranscriptBlock block={{ type: "text", text: part.text }} key={`system-${index}`} />
          ))}
        </ExchangeSection>
      )}

      {messages.length > 0 && (
        <ExchangeSection title="messages">
          {messages.map((message, messageIndex) => (
            <article
              className="canvas-exchange__message"
              data-role={message.role}
              // biome-ignore lint/suspicious/noArrayIndexKey: fetched payload snapshot, never reordered
              key={`message-${messageIndex}`}
            >
              <header className="canvas-exchange__message-role">{message.role}</header>
              {message.content.map((block, index) => (
                <TranscriptBlock block={block} key={blockKey(block, index)} />
              ))}
            </article>
          ))}
        </ExchangeSection>
      )}

      {responseContent.length > 0 && (
        <ExchangeSection title="response">
          {responseContent.map((block, index) => (
            <TranscriptBlock block={block} key={blockKey(block, index)} />
          ))}
        </ExchangeSection>
      )}

      {tools.length > 0 && (
        <ExchangeSection title="tools">
          {tools.map((tool) => (
            <details className="canvas-exchange__tool" key={tool.name}>
              <summary>
                <span className="canvas-exchange__tool-name">{tool.name}</span>
                <span className="canvas-exchange__tool-description">{tool.description}</span>
              </summary>
              <pre>{JSON.stringify(tool.input_schema, null, 2)}</pre>
            </details>
          ))}
        </ExchangeSection>
      )}
    </div>
  );
}

/** Transport panel: diagnostics first, then the raw transport artifacts. */
export function ExchangeTransportPanel({ detail }: { detail: ExchangeDetail }): ReactElement {
  return (
    <div className="canvas-exchange__transport">
      {detail.transport_diagnostics.length > 0 && (
        <ul className="canvas-exchange__diagnostics">
          {detail.transport_diagnostics.map((diagnostic) => (
            <DiagnosticRow diagnostic={diagnostic} key={diagnostic.code} />
          ))}
        </ul>
      )}
      <ExchangeJsonPanel emptyLabel="No transport data" value={detail.transport} />
    </div>
  );
}

function ExchangeSection({
  children,
  title,
}: {
  children: React.ReactNode;
  title: string;
}): ReactElement {
  return (
    <section className="canvas-exchange__section">
      <h3 className="canvas-exchange__section-title">{title}</h3>
      {children}
    </section>
  );
}

function CodexEventRow({ event }: { event: CodexSemanticEvent }): ReactElement {
  return (
    <li className="canvas-exchange__event">
      <span className="canvas-exchange__event-seq">{event.seq}</span>
      <span className="canvas-exchange__event-kind">{event.kind}</span>
      <span className="canvas-exchange__event-source">{event.source}</span>
      <details className="canvas-exchange__event-data">
        <summary>data</summary>
        <pre>{JSON.stringify(event.data, null, 2)}</pre>
      </details>
    </li>
  );
}

function DiagnosticRow({ diagnostic }: { diagnostic: TransportDiagnostic }): ReactElement {
  return (
    <li className="canvas-exchange__diagnostic" data-severity={diagnostic.severity}>
      <header className="canvas-exchange__diagnostic-header">
        <span className="canvas-exchange__diagnostic-severity">{diagnostic.severity}</span>
        <span className="canvas-exchange__diagnostic-code">{diagnostic.code}</span>
      </header>
      <p className="canvas-exchange__diagnostic-summary">{diagnostic.summary}</p>
      {diagnostic.detail && (
        <p className="canvas-exchange__diagnostic-detail">{diagnostic.detail}</p>
      )}
      {diagnostic.operator_checks.length > 0 && (
        <ul className="canvas-exchange__diagnostic-checks">
          {diagnostic.operator_checks.map((check) => (
            <li key={check}>{check}</li>
          ))}
        </ul>
      )}
    </li>
  );
}
