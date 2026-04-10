/**
 * Shared atoms for the detail view.
 *
 * Each primitive has one job and one look. Combined, they give
 * every panel inside the Inspect tab a consistent identity.
 */

import type { ReactNode } from "react";

// ── SectionRule ────────────────────────────────────────────────────
// An uppercase label flanked by a pair of gradient hairlines that
// fade toward the container edges. Used as a top-level divider
// between sections inside a tab body.

export function SectionRule({ children }: { children: ReactNode }) {
  return (
    <div className="section-rule mb-4">
      <span className="label">{children}</span>
    </div>
  );
}

// ── MetricCell ─────────────────────────────────────────────────────
// Label above, numeric value below. The label uses the global
// .label class (uppercase, tracked, readable grey). The value uses
// .metric-num for tabular figures and slashed zero.

export function MetricCell({
  label,
  value,
  accent,
  size = "md",
}: {
  label: string;
  value: string | number;
  accent?: string;
  size?: "sm" | "md" | "lg";
}) {
  const valueSize = size === "lg" ? "text-[16px]" : size === "sm" ? "text-[12px]" : "text-[14px]";
  return (
    <div className="flex flex-col gap-2">
      <span className="label">{label}</span>
      <span className={`metric-num font-medium ${valueSize} ${accent ?? "text-txt"}`}>{value}</span>
    </div>
  );
}

// ── Panel ──────────────────────────────────────────────────────────
// The default elevated surface. Header slot is optional; when
// present it sits above a hairline rule and carries the panel's
// title plus any right-aligned metadata.

export function Panel({
  title,
  meta,
  children,
  tone,
}: {
  title?: string;
  meta?: ReactNode;
  children: ReactNode;
  tone?: "request" | "response" | "neutral";
}) {
  // Tone adds a subtle coloured tick to the left of the title.
  const tickColour =
    tone === "request" ? "bg-sky/50" : tone === "response" ? "bg-sage/50" : "bg-txt-3/40";

  return (
    <div className="card top-highlight">
      {title && (
        <>
          <div className="flex items-center justify-between gap-3 px-5 py-3">
            <div className="flex items-center gap-2.5">
              <span className={`inline-block h-3 w-px ${tickColour}`} />
              <span className="label">{title}</span>
            </div>
            {meta && <div className="flex items-center gap-2 text-[10px] text-txt-2">{meta}</div>}
          </div>
          <div className="hairline-x" />
        </>
      )}
      <div>{children}</div>
    </div>
  );
}

// ── MetricGrid ─────────────────────────────────────────────────────
// A tight grid of MetricCells with hairline dividers between them.
// The dividers are drawn by bg-edge showing through a 1px gap so
// no borders are needed on the cells themselves.

export function MetricGrid({ cols, children }: { cols: 2 | 3 | 4; children: ReactNode }) {
  const gridCols = cols === 2 ? "grid-cols-2" : cols === 3 ? "grid-cols-3" : "grid-cols-4";
  return <div className={`grid ${gridCols} gap-px bg-edge-subtle`}>{children}</div>;
}

export function MetricGridCell({ children }: { children: ReactNode }) {
  return <div className="bg-surface px-5 py-4">{children}</div>;
}

// ── KeyValueRow ────────────────────────────────────────────────────
// Horizontal key/value display with the key left and the value
// right. Used in pipeline rule lists and similar compact data.

export function KeyValueRow({
  label,
  value,
  valueClass,
}: {
  label: string;
  value: ReactNode;
  valueClass?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5 text-[11px]">
      <span className="text-txt-2">{label}</span>
      <span className={valueClass ?? "text-txt-3 metric-num"}>{value}</span>
    </div>
  );
}
