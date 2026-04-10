import { useState } from "react";

interface JsonViewProps {
  payload: Record<string, unknown> | null;
  emptyLabel?: string;
}

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
      className="btn cursor-pointer border border-edge bg-surface px-3 py-1 text-[10px] uppercase tracking-wider text-txt-2 hover:text-txt hover:bg-raised transition-colors"
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

export function JsonView({ payload, emptyLabel = "No data" }: JsonViewProps) {
  const content = payload ? JSON.stringify(payload, null, 2) : "";
  const lineCount = content ? content.split("\n").length : 0;

  return (
    <div className="flex h-full flex-col">
      {/* Metadata strip */}
      <div className="flex items-center justify-between px-8 py-3">
        <span className="label metric-num">{lineCount.toLocaleString()} lines</span>
        <CopyButton text={content} disabled={!content} />
      </div>

      <div className="hairline-x" />

      {/* JSON content */}
      <div className="flex-1 overflow-auto">
        {content ? (
          <pre
            className="text-[11px] leading-[1.75] text-txt-2 whitespace-pre-wrap px-8 py-6"
            style={{
              fontFeatureSettings: "'tnum', 'zero'",
            }}
          >
            {content}
          </pre>
        ) : (
          <div className="flex items-center justify-center h-full">
            <span className="label">{emptyLabel}</span>
          </div>
        )}
      </div>
    </div>
  );
}
