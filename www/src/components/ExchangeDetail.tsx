import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { fetchExchange } from "../api";
import { InspectTab } from "./detail/InspectTab";
import { JsonView } from "./detail/JsonView";

interface ExchangeDetailProps {
  id: string;
}

type DetailTab = "inspect" | "request" | "response";

export function ExchangeDetail({ id }: ExchangeDetailProps) {
  const [tab, setTab] = useState<DetailTab>("inspect");

  const {
    data: detail,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["exchange", id],
    queryFn: () => fetchExchange(id),
  });

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="flex items-center gap-2.5">
          <span className="inline-block h-1 w-1 rounded-full bg-sky pulse-dot" />
          <span className="label">Loading exchange</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="border border-rose/25 bg-rose/5 px-4 py-2.5 text-[11px] text-rose">
          {error instanceof Error ? error.message : "Failed to load exchange"}
        </p>
      </div>
    );
  }

  if (!detail) return null;

  const { entry } = detail;
  const ts = new Date(entry.ts);
  const dateStr = ts.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
  const timeStr = ts.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  return (
    <div className="flex h-full flex-col overflow-hidden fade-in">
      {/* Header */}
      <div className="top-highlight bg-surface px-8 py-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h2 className="truncate text-[15px] font-semibold tracking-tight text-txt">
              {entry.model.replace(/^anthropic\//, "")}
            </h2>
            <div className="mt-2 flex items-center gap-3 text-[10px]">
              <span className="border border-edge bg-canvas px-2 py-0.5 label">
                {entry.provider}
              </span>
              <span className="text-txt-2 tabular-nums">{dateStr}</span>
              <span className="text-edge-strong">&middot;</span>
              <span className="text-txt-2 metric-num">{timeStr}</span>
              {entry.mutated_manually && (
                <>
                  <span className="text-edge-strong">&middot;</span>
                  <span className="flex items-center gap-1.5 text-amber">
                    <span className="inline-block h-1 w-1 rounded-full bg-amber" />
                    <span className="label text-amber">edited</span>
                  </span>
                </>
              )}
            </div>
          </div>
          <div className="shrink-0 flex flex-col items-end gap-1">
            <span className="label">id</span>
            <span className="text-[10px] text-txt-2 metric-num">{entry.id.slice(0, 8)}</span>
          </div>
        </div>
      </div>

      {/* Tab bar — pressed-key active state */}
      <div className="flex border-y border-edge">
        {(["inspect", "request", "response"] as const).map((t) => {
          const disabled = t === "response" && detail.response_ir == null;
          return (
            <button
              key={t}
              type="button"
              onClick={() => !disabled && setTab(t)}
              disabled={disabled}
              className={`relative cursor-pointer px-8 py-3 text-[10px] font-medium uppercase tracking-[0.14em] transition-all duration-150 ${
                tab === t
                  ? "tab-pressed text-txt"
                  : disabled
                    ? "tab-rest text-txt-3/40 cursor-not-allowed"
                    : "tab-rest text-txt-3 hover:text-txt-2"
              }`}
            >
              {t}
            </button>
          );
        })}
        <div className="flex-1 tab-rest" />
      </div>

      {/* Tab content — request tabs default to what was actually sent to
          the provider (curated IR when the pipeline or a breakpoint edit
          mutated the request), falling back to the original IR otherwise. */}
      <div className="flex-1 overflow-y-auto">
        {tab === "inspect" ? (
          <InspectTab detail={detail} />
        ) : tab === "request" ? (
          <JsonView payload={detail.request_curated_ir ?? detail.request_ir} />
        ) : (
          <JsonView payload={detail.response_ir} emptyLabel="No response data" />
        )}
      </div>
    </div>
  );
}
