import { type ReactNode, useMemo } from "react";

interface ExchangePreviewProps {
  text: string;
  stopReason?: string | null;
}

type PreviewKind = "json" | "code" | "xml" | "plain";

interface ClassifiedPreview {
  kind: PreviewKind;
  pill: string | null;
  body: string;
  mono: boolean;
}

const MAX_LINES = 3;

export function classifyPreview(raw: string): ClassifiedPreview {
  const text = raw.trim();
  if (!text) return { kind: "plain", pill: null, body: "", mono: false };

  const head = text.slice(0, 80);
  const fenceMatch = head.match(/^```([A-Za-z0-9_+-]+)?/);
  if (fenceMatch) {
    const lang = fenceMatch[1]?.toUpperCase() ?? "CODE";
    const body = text.replace(/^```[A-Za-z0-9_+-]*\r?\n?/, "").replace(/\r?\n?```\s*$/, "");
    return { kind: "code", pill: lang, body: takeLines(body, MAX_LINES), mono: true };
  }

  if (head.startsWith("{") || head.startsWith("[")) {
    try {
      const parsed = JSON.parse(text);
      const pretty = JSON.stringify(parsed, null, 2);
      return { kind: "json", pill: "JSON", body: takeLines(pretty, MAX_LINES), mono: true };
    } catch {
      return { kind: "json", pill: "JSON", body: takeLines(text, MAX_LINES), mono: true };
    }
  }

  const xmlMatch = head.match(/^<([A-Za-z][A-Za-z0-9_-]*)\b[^>]*>/);
  const tag = xmlMatch?.[1];
  if (tag) {
    const closePattern = new RegExp(`</${tag}\\s*>\\s*$`);
    const body = text
      .replace(/^<[A-Za-z][^>]*>\s*/, "")
      .replace(closePattern, "")
      .trim();
    return { kind: "xml", pill: tag.toUpperCase(), body: body || text, mono: false };
  }

  return { kind: "plain", pill: null, body: text, mono: false };
}

function takeLines(text: string, maxLines: number): string {
  const lines = text.split("\n");
  if (lines.length <= maxLines) return text;
  return `${lines.slice(0, maxLines).join("\n")}\n\u2026`;
}

export function ExchangePreview({ text, stopReason }: ExchangePreviewProps) {
  const classified = useMemo(() => classifyPreview(text), [text]);
  const { pill, body, mono } = classified;

  const stopReasonNode: ReactNode = stopReason ? (
    <span className="ml-2 text-[11px] uppercase text-txt-3">· {stopReason}</span>
  ) : null;

  if (mono) {
    return (
      <span className="flex min-w-0 flex-col gap-1.5">
        <span className="flex items-center gap-2">
          {pill && <span className="chip shrink-0 px-2 py-0.5 text-[9px] text-txt-3">{pill}</span>}
          {stopReasonNode}
        </span>
        <span className="block max-h-[60px] min-w-0 overflow-hidden whitespace-pre font-mono text-[11px] leading-snug text-txt-2">
          {body}
        </span>
      </span>
    );
  }

  return (
    <span className="flex min-w-0 items-start gap-2">
      {pill && (
        <span className="chip mt-0.5 shrink-0 px-2 py-0.5 text-[9px] text-txt-3">{pill}</span>
      )}
      <span className="line-clamp-3 min-w-0 flex-1 text-[13px] leading-snug text-txt-2">
        {body}
        {stopReasonNode}
      </span>
    </span>
  );
}
