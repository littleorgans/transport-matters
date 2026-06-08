import "./resource-primitives.css";

/**
 * Code-style text with a line-number gutter, shared by the text and tool-output
 * viewers. Renders each line as plain text (React escapes it), so untrusted
 * transcript content can never inject markup. Empty lines keep their height via
 * a non-breaking space so the gutter stays aligned.
 */
export function CodeText({ text, startLine = 1 }: { text: string; startLine?: number }) {
  const lines = text.split("\n");
  return (
    <div className="canvas-code">
      {lines.map((line, index) => {
        const lineNumber = startLine + index;
        return (
          <div className="canvas-code__row" key={`l${lineNumber}`}>
            <span aria-hidden="true" className="canvas-code__gutter">
              {lineNumber}
            </span>
            <code className="canvas-code__text">{line.length === 0 ? " " : line}</code>
          </div>
        );
      })}
    </div>
  );
}
