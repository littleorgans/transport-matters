import { useEffect, useState } from "react";
import { fetchExchange } from "../api";
import type { ExchangeDetail as ExchangeDetailType } from "../types";
import { InspectTab } from "./detail/InspectTab";
import { JsonTab } from "./detail/JsonTab";

interface ExchangeDetailProps {
  id: string;
}

type DetailTab = "inspect" | "json";

export function ExchangeDetail({ id }: ExchangeDetailProps) {
  const [detail, setDetail] = useState<ExchangeDetailType | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<DetailTab>("inspect");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchExchange(id)
      .then((data) => {
        if (!cancelled) {
          setDetail(data);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load exchange");
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="flex items-center gap-2.5 text-[11px] text-txt-3">
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-sky pulse-dot" />
          Loading exchange
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="rounded-md border border-rose/20 bg-rose/5 px-4 py-2.5 text-[11px] text-rose">
          {error}
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
      <div className="border-b border-edge bg-surface px-6 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h2 className="truncate text-[14px] font-semibold text-txt">
              {entry.model.replace(/^anthropic\//, "")}
            </h2>
            <div className="mt-1.5 flex items-center gap-2.5 text-[10px] text-txt-3">
              <span className="rounded bg-raised px-2 py-0.5 text-txt-2">{entry.provider}</span>
              <span>{dateStr}</span>
              <span className="text-edge">/</span>
              <span className="tabular-nums">{timeStr}</span>
              {entry.mutated_manually && (
                <span className="rounded bg-amber/10 border border-amber/20 px-1.5 py-0.5 text-amber">
                  edited
                </span>
              )}
            </div>
          </div>
          <span className="shrink-0 text-[10px] text-txt-3 tabular-nums pt-0.5">
            {entry.id.slice(0, 8)}
          </span>
        </div>

        {/* Tab bar */}
        <div className="mt-4 flex gap-1">
          {(["inspect", "json"] as const).map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setTab(t)}
              className={`btn cursor-pointer rounded-md px-3 py-1.5 text-[11px] font-medium transition-colors ${
                tab === t ? "bg-raised text-txt" : "text-txt-3 hover:text-txt-2 hover:bg-raised/50"
              }`}
            >
              {t === "inspect" ? "Inspect" : "JSON"}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto">
        {tab === "inspect" ? (
          <InspectTab detail={detail} />
        ) : (
          <JsonTab requestIr={detail.request_ir} responseIr={detail.response_ir} />
        )}
      </div>
    </div>
  );
}
