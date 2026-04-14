import type { ReactNode } from "react";
import { useMemo } from "react";

/** Colorize a single line of pre-formatted JSON (keys, strings, numbers, booleans, null). */
export function colorizeLine(line: string, lineIdx: number): ReactNode[] {
  const re =
    /("(?:[^"\\]|\\.)*")\s*:|("(?:[^"\\]|\\.)*")|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\b|\b(true|false)\b|\b(null)\b/g;
  const parts: ReactNode[] = [];
  let last = 0;
  let i = 0;
  let match: RegExpExecArray | null;

  // biome-ignore lint/suspicious/noAssignInExpressions: standard regex exec loop
  while ((match = re.exec(line)) !== null) {
    if (match.index > last) parts.push(line.slice(last, match.index));
    const key = `${lineIdx}-${i++}`;
    if (match[1] != null) {
      parts.push(
        <span key={key} className="text-sky">
          {match[1]}
        </span>,
      );
      parts.push(line.slice(match.index + match[1].length, match.index + match[0].length));
    } else if (match[2] != null) {
      parts.push(
        <span key={key} className="text-sage">
          {match[2]}
        </span>,
      );
    } else if (match[3] != null) {
      parts.push(
        <span key={key} className="text-lavender">
          {match[3]}
        </span>,
      );
    } else if (match[4] != null) {
      parts.push(
        <span key={key} className="text-amber">
          {match[4]}
        </span>,
      );
    } else if (match[5] != null) {
      parts.push(
        <span key={key} className="text-txt-3">
          {match[5]}
        </span>,
      );
    }
    last = match.index + match[0].length;
  }
  if (last < line.length) parts.push(line.slice(last));
  return parts;
}

/** Try to pretty-print as colorized JSON; fall back to plain text. */
export function ColorizedPre({ text }: { text: string }) {
  const parsed = useMemo(() => {
    try {
      const obj = JSON.parse(text);
      return JSON.stringify(obj, null, 2);
    } catch {
      return null;
    }
  }, [text]);

  if (parsed) {
    const lines = parsed.split("\n");
    return (
      <pre className="mt-2 ml-[26px] bg-canvas p-3 mx-4 mb-1 text-[12px] whitespace-pre-wrap border border-edge-subtle font-mono">
        {lines.map((line, idx) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: stable line order
          <div key={idx}>{colorizeLine(line, idx)}</div>
        ))}
      </pre>
    );
  }

  return (
    <pre className="mt-2 ml-[26px] bg-canvas p-3 mx-4 mb-1 text-[12px] text-txt-2 whitespace-pre-wrap border border-edge-subtle">
      {text}
    </pre>
  );
}
