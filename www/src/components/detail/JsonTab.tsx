import { useState } from "react";

interface JsonTabProps {
  requestIr: Record<string, unknown>;
  responseIr: Record<string, unknown> | null;
}

type JsonView = "request" | "response";

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      className="btn cursor-pointer rounded-md border border-edge bg-surface px-2.5 py-1 text-[10px] text-txt-3 hover:text-txt-2 hover:bg-raised transition-colors"
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

export function JsonTab({ requestIr, responseIr }: JsonTabProps) {
  const [view, setView] = useState<JsonView>("request");
  const hasResponse = responseIr != null;

  const content =
    view === "request"
      ? JSON.stringify(requestIr, null, 2)
      : responseIr
        ? JSON.stringify(responseIr, null, 2)
        : "";

  return (
    <div className="flex h-full flex-col">
      {/* Toggle bar */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-edge">
        <div className="flex gap-1">
          <button
            type="button"
            onClick={() => setView("request")}
            className={`btn cursor-pointer rounded-md px-3 py-1.5 text-[11px] font-medium transition-colors ${
              view === "request" ? "bg-raised text-txt" : "text-txt-3 hover:text-txt-2"
            }`}
          >
            Request IR
          </button>
          <button
            type="button"
            onClick={() => setView("response")}
            disabled={!hasResponse}
            className={`btn cursor-pointer rounded-md px-3 py-1.5 text-[11px] font-medium transition-colors ${
              view === "response" ? "bg-raised text-txt" : "text-txt-3 hover:text-txt-2"
            }`}
          >
            Response IR
          </button>
        </div>
        <CopyButton text={content} />
      </div>

      {/* JSON content */}
      <div className="flex-1 overflow-auto px-6 py-4">
        {content ? (
          <pre className="text-[11px] leading-[1.7] text-txt-2 whitespace-pre-wrap">{content}</pre>
        ) : (
          <div className="flex items-center justify-center h-full">
            <span className="text-[11px] text-txt-3">No response data available</span>
          </div>
        )}
      </div>
    </div>
  );
}
