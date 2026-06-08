import { useState } from "react";
import type { TextContentResponse } from "../../api/resourceContent";
import { renderMarkdown } from "./markdown";
import { CodeText } from "./primitives/CodeText";
import { CopyButton } from "./primitives/CopyButton";
import { TruncationNote } from "./primitives/TruncationNote";
import "./markdown-viewer.css";

type Mode = "rendered" | "source";

/**
 * Markdown resource viewer: rendered output with a source toggle. The rendered
 * path goes through the dependency-free, XSS-safe renderer (no raw-HTML escape
 * hatch); the source path shows the raw text with line numbers. Copy controls
 * satisfy the spec's tool-output requirement too.
 */
export function MarkdownResourceViewer({ content }: { content: TextContentResponse }) {
  const [mode, setMode] = useState<Mode>("rendered");
  return (
    <div className="canvas-md">
      <div className="canvas-md__toolbar">
        <fieldset aria-label="Markdown view mode" className="canvas-md__toggle">
          <button
            aria-pressed={mode === "rendered"}
            className="canvas-button"
            onClick={() => setMode("rendered")}
            type="button"
          >
            Rendered
          </button>
          <button
            aria-pressed={mode === "source"}
            className="canvas-button"
            onClick={() => setMode("source")}
            type="button"
          >
            Source
          </button>
        </fieldset>
        <CopyButton label="Copy source" value={content.text} />
      </div>
      {content.truncated && (
        <TruncationNote
          className="canvas-md__truncated"
          message="Partial content shown (source truncated by the server)."
        />
      )}
      {mode === "rendered" ? (
        <div className="canvas-md__body">{renderMarkdown(content.text)}</div>
      ) : (
        <CodeText text={content.text} />
      )}
    </div>
  );
}
