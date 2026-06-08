import type { ReactElement } from "react";
import type { TextContentResponse } from "../../api/resourceContent";
import { CodeText } from "./primitives/CodeText";
import { CopyButton } from "./primitives/CopyButton";

/**
 * Plain-text resource viewer body: the captured text rendered with a
 * line-number gutter plus a copy control. Range and truncation are surfaced as
 * a short note so the operator knows the view is partial. The parent pane owns
 * the provenance label and frame; this renders only the inner body.
 */
export function TextResourceViewer({ content }: { content: TextContentResponse }): ReactElement {
  const { range, truncated } = content;
  return (
    <div className="canvas-text">
      <div className="canvas-text__toolbar">
        <CopyButton label="Copy" value={content.text} />
      </div>
      {range ? (
        <p className="canvas-text__note">
          Showing bytes {range.start}–{range.end} of {range.total}
        </p>
      ) : (
        truncated && (
          <p className="canvas-text__note">Partial content shown (truncated by the server).</p>
        )
      )}
      <div className="canvas-text__body">
        <CodeText text={content.text} />
      </div>
    </div>
  );
}
