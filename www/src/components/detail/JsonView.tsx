import { useVirtualizer } from "@tanstack/react-virtual";
import { useMemo, useRef, useState } from "react";
import { colorizeLine } from "../../lib/colorizeLine";

interface JsonViewProps {
  payload: object | null;
  emptyLabel?: string;
}

const LINE_HEIGHT = 23; // 13px font * 1.75 leading

function CopyButton({ text, disabled }: { text: string; disabled?: boolean }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    if (disabled) return;
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      disabled={disabled}
      className="btn cursor-pointer border border-edge bg-surface px-3 py-1 text-[12px] uppercase tracking-wider text-txt-2 hover:text-txt hover:bg-raised transition-colors"
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

export function JsonView({ payload, emptyLabel = "No data" }: JsonViewProps) {
  const content = payload ? JSON.stringify(payload, null, 2) : "";
  const lines = useMemo(() => (content ? content.split("\n") : []), [content]);
  const scrollRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: lines.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => LINE_HEIGHT,
    overscan: 30,
  });

  return (
    <div className="flex h-full flex-col">
      {/* Metadata strip */}
      <div className="flex items-center justify-between px-8 py-3">
        <span className="label metric-num">{lines.length.toLocaleString()} lines</span>
        <CopyButton text={content} disabled={!content} />
      </div>

      <div className="hairline-x" />

      {/* JSON content */}
      <div ref={scrollRef} className="flex-1 overflow-auto">
        {lines.length > 0 ? (
          <div
            className="relative px-8"
            style={{ height: virtualizer.getTotalSize() + 48, paddingTop: 24, paddingBottom: 24 }}
          >
            {virtualizer.getVirtualItems().map((vRow) => (
              <div
                key={vRow.index}
                className="absolute left-0 right-0 px-8 text-[13px] text-txt-3 whitespace-pre font-mono"
                style={{
                  height: LINE_HEIGHT,
                  transform: `translateY(${vRow.start + 24}px)`,
                  fontFeatureSettings: "'tnum', 'zero'",
                }}
              >
                {colorizeLine(lines[vRow.index] ?? "", vRow.index)}
              </div>
            ))}
          </div>
        ) : (
          <div className="flex items-center justify-center h-full">
            <span className="label">{emptyLabel}</span>
          </div>
        )}
      </div>
    </div>
  );
}
