import { type ReactElement, useState } from "react";
import type { JsonContentResponse } from "../../api/resourceContent";
import { CodeText } from "./primitives/CodeText";
import { CopyButton } from "./primitives/CopyButton";
import { JsonTree } from "./primitives/JsonTree";

type Mode = "tree" | "raw";

/**
 * JSON resource viewer body, shared by the plain-json and native-record
 * provenances (selection happens upstream; this just renders the value). A tree
 * view goes through the collapsible JsonTree primitive; the raw view shows the
 * server-provided text when present, otherwise a pretty-printed fallback, with
 * line numbers via CodeText. Renders the inner body only — no provenance label
 * or pane frame.
 */
export function JsonResourceViewer({ content }: { content: JsonContentResponse }): ReactElement {
  const [mode, setMode] = useState<Mode>("tree");
  const rawText = content.text ?? JSON.stringify(content.value, null, 2);

  return (
    <div className="canvas-jsonview">
      <div className="canvas-jsonview__toolbar">
        <fieldset aria-label="JSON view mode" className="canvas-jsonview__toggle">
          <button
            aria-pressed={mode === "tree"}
            className="canvas-button"
            onClick={() => setMode("tree")}
            type="button"
          >
            Tree
          </button>
          <button
            aria-pressed={mode === "raw"}
            className="canvas-button"
            onClick={() => setMode("raw")}
            type="button"
          >
            Raw
          </button>
        </fieldset>
        <CopyButton label="Copy" value={rawText} />
      </div>
      {content.truncated && (
        <p className="canvas-jsonview__note">Partial content shown (truncated by the server).</p>
      )}
      {mode === "tree" ? <JsonTree value={content.value} /> : <CodeText text={rawText} />}
    </div>
  );
}
