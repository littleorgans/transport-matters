import type { ReactElement } from "react";
import type { BinaryContentResponse } from "../../api/resourceContent";

/**
 * Binary resource viewer body: a metadata definition list plus an
 * "Open externally" action. Inline-able binaries cannot be rendered in place,
 * so the value here is the provenance metadata and a safe way out to the bytes.
 * When no download URL exists the action degrades to a disabled button so the
 * affordance stays visible. The parent pane owns the provenance label and
 * frame; this renders only the inner body.
 */
export function BinaryResourceViewer({
  content,
}: {
  content: BinaryContentResponse;
}): ReactElement {
  const rows: ReadonlyArray<{ label: string; value: ReactElement | string }> = [
    { label: "Title", value: content.title },
    { label: "Media type", value: content.mediaType ?? "unknown" },
    { label: "Size", value: formatBytes(content.contentLength) },
    {
      label: "SHA-256",
      value: <span className="canvas-binary__hash">{content.sha256 ?? "unavailable"}</span>,
    },
  ];
  return (
    <div className="canvas-binary">
      <dl className="canvas-binary__meta">
        {rows.map((row) => (
          <div className="canvas-binary__row" key={row.label}>
            <dt className="canvas-binary__label">{row.label}</dt>
            <dd className="canvas-binary__value">{row.value}</dd>
          </div>
        ))}
      </dl>
      <div className="canvas-binary__actions">
        {content.downloadUrl !== null ? (
          <a
            className="canvas-button"
            download
            href={content.downloadUrl}
            rel="noopener noreferrer"
            target="_blank"
          >
            Open externally
          </a>
        ) : (
          <button className="canvas-button" disabled type="button">
            Open externally
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * Render a byte count as bytes/KB/MB with one decimal place. Deterministic and
 * locale-independent so tests can assert exact output. Null becomes "unknown".
 */
export function formatBytes(bytes: number | null): string {
  if (bytes === null) return "unknown";
  const kb = 1024;
  const mb = kb * 1024;
  if (bytes < kb) return `${bytes} bytes`;
  if (bytes < mb) return `${(bytes / kb).toFixed(1)} KB`;
  return `${(bytes / mb).toFixed(1)} MB`;
}
