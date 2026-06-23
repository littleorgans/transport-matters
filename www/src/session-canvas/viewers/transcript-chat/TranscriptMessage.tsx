import { blockKey, blockSummary } from "../../../components/detail/ContentBlocks";
import { formatClockTime } from "../../../lib/formatting";
import type { ContentBlock } from "../../../types";
import type { TranscriptMessageModel } from "../../stream/mapIrToChat";

export interface TranscriptMessageProps {
  message: TranscriptMessageModel;
  /** When true, the denylist hides this record; it renders dimmed (reveal-on-toggle). */
  hidden?: boolean;
}

export function TranscriptMessage({ message, hidden = false }: TranscriptMessageProps) {
  return (
    <article
      className="canvas-transcript-message"
      data-kind={message.kind}
      data-role={message.role}
      data-hidden={hidden || undefined}
    >
      <header className="canvas-transcript-message__header">
        <span>{message.role}</span>
        {message.wireLabel ? (
          <span className="canvas-transcript-message__wire-label">{message.wireLabel}</span>
        ) : null}
        <span>seq {message.seq}</span>
        {message.timestamp ? <span>{formatClockTime(message.timestamp)}</span> : null}
      </header>
      <div className="canvas-transcript-message__blocks">
        {message.blocks.map((block, index) => (
          <TranscriptBlock block={block} key={blockKey(block, index)} />
        ))}
      </div>
      {message.nativePayload !== null ? (
        <details className="canvas-transcript-message__raw">
          <summary>view raw</summary>
          <pre>{JSON.stringify(message.nativePayload, null, 2)}</pre>
        </details>
      ) : null}
    </article>
  );
}

function TranscriptBlock({ block }: { block: ContentBlock }) {
  if (block.type === "text") {
    return (
      <pre className="canvas-transcript-block canvas-transcript-block--text">{block.text}</pre>
    );
  }
  if (block.type === "thinking") {
    return (
      <details className="canvas-transcript-block canvas-transcript-block--thinking">
        <summary>{blockSummary(block)}</summary>
        <pre>{block.text}</pre>
      </details>
    );
  }
  if (block.type === "image") {
    return <ImageBlock block={block} />;
  }
  return (
    <details className="canvas-transcript-block canvas-transcript-block--structured">
      <summary>{blockSummary(block)}</summary>
      <pre>{JSON.stringify(block, null, 2)}</pre>
    </details>
  );
}

function ImageBlock({ block }: { block: Extract<ContentBlock, { type: "image" }> }) {
  const artifactHash = block.source.artifact_hash;
  const mediaType = block.source.media_type;
  return (
    <div className="canvas-transcript-block canvas-transcript-block--image">
      <span>image</span>
      {typeof artifactHash === "string" ? <span>artifact {artifactHash}</span> : null}
      {typeof mediaType === "string" ? <span>{mediaType}</span> : null}
    </div>
  );
}
