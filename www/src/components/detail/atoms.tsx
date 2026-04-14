import type { ReactNode } from "react";

// Master bar — single click-to-toggle-all strip used at the head of a
// `card-flush` container. Every section follows this same shape: a chip
// (label + tone), a unit count, and an optional `extras` slot for
// section-specific indicators (e.g. "modified" or "overrides"). The
// keyboard path matches the click path so Enter/Space folds the whole
// section too.
interface MasterBarProps {
  label: string;
  tone?: { text: string; bg: string };
  count: number;
  countUnit: string;
  extras?: ReactNode;
  onToggleAll: () => void;
}

export function MasterBar({ label, tone, count, countUnit, extras, onToggleAll }: MasterBarProps) {
  const resolved = tone ?? { text: "text-txt-2", bg: "bg-raised" };
  return (
    <button
      type="button"
      onClick={onToggleAll}
      className={`flex w-full cursor-pointer items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-raised focus:outline-none focus-visible:bg-raised ${resolved.bg}`}
    >
      <span className={`chip ${resolved.text}`}>{label}</span>
      <span className="text-[13px] text-txt-3 metric-num">
        {count} {countUnit}
        {count !== 1 ? "s" : ""}
      </span>
      {extras}
    </button>
  );
}

// Tints for master bars, keyed by section. Kept next to `MasterBar`
// so consumers only need one import.
export const SECTION_TONE: Record<string, { text: string; bg: string }> = {
  system: { text: "text-lavender", bg: "bg-lavender/5" },
  user: { text: "text-sky", bg: "bg-sky/5" },
  assistant: { text: "text-sage", bg: "bg-sage/5" },
  response: { text: "text-sage", bg: "bg-sage/5" },
};

export function SectionRule({ children }: { children: ReactNode }) {
  return (
    <div className="section-rule mb-4">
      <span className="label">{children}</span>
    </div>
  );
}

export function OriginalPreview({ text }: { text: string }) {
  return (
    <div className="space-y-1">
      <span className="label text-txt-3">Original</span>
      <pre className="max-h-32 overflow-auto bg-canvas p-3 text-[12px] text-txt-3 whitespace-pre-wrap border border-edge-subtle">
        {text}
      </pre>
    </div>
  );
}

export const inputClass =
  "w-full min-h-24 resize-none field-sizing-content bg-canvas px-3 py-2 text-[13px] text-txt border border-edge focus:border-accent/50 focus:outline-none transition-colors font-mono";
