import type { ReactNode } from "react";
import { Toggle } from "../Toggle";

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

// Shared header shell for editor rows that share the same composite
// shape: a toggle on the left, a stack of leading chips (index / type
// / cached / error — caller decides), a modified dot, a truncating
// preview string, and a size label. The whole header is one click-
// target that fires ``onToggleExpanded``; the Toggle lives inside a
// stopPropagation island so flipping the applied state never collapses
// the row. Expanded body is rendered by the caller as ``children`` —
// different row kinds need different bodies (textarea vs. ColorizedPre)
// so the shell doesn't prescribe one.
//
// The per-row RESET affordance has moved into the ``TextOverrideEditor``
// tab bar where it sits adjacent to EDIT | DIFF. Reset is an edit-mode
// action, and clustering it with the edit-mode controls keeps the row
// header quiet for scanning.
interface CompositeEditableRowProps {
  checked: boolean;
  onToggle: () => void;
  toggleLabel: string;
  leadingChips?: ReactNode;
  isModified: boolean;
  preview: string;
  size: ReactNode;
  onToggleExpanded: () => void;
  children?: ReactNode;
  readOnly?: boolean;
}

export function CompositeEditableRow({
  checked,
  onToggle,
  toggleLabel,
  leadingChips,
  isModified,
  preview,
  size,
  onToggleExpanded,
  children,
  readOnly,
}: CompositeEditableRowProps) {
  // Read-only mode: no toggle control (user can't flip state), but keep
  // the opacity dimming driven by ``checked`` so a synthesised
  // ``*_toggle: false`` override reads as "this block was disabled" the
  // same way the editor renders it live. Without the dim, the Inspect
  // tab's "N MODIFIED" count disagrees with the block rows it's
  // supposedly counting.
  if (readOnly) {
    return (
      <div className={`transition-opacity ${checked ? "" : "opacity-40"}`}>
        <button
          type="button"
          onClick={onToggleExpanded}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              onToggleExpanded();
            }
          }}
          className="flex w-full cursor-pointer items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-raised focus:outline-none focus-visible:bg-raised"
        >
          {leadingChips}
          {isModified && <span className="h-1 w-1 shrink-0 rounded-full bg-amber" />}
          <span className="flex-1 min-w-0 truncate text-[13px] leading-5 text-txt-2">
            {preview}
          </span>
          {size}
        </button>
        {children}
      </div>
    );
  }

  return (
    <div className={`transition-opacity ${checked ? "" : "opacity-40"}`}>
      {/* biome-ignore lint/a11y/useSemanticElements: composite row wraps a Toggle button; button-in-button is invalid HTML */}
      <div
        role="button"
        tabIndex={0}
        onClick={onToggleExpanded}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            onToggleExpanded();
          }
        }}
        className="flex cursor-pointer items-center gap-3 px-4 py-2.5 transition-colors hover:bg-raised focus:outline-none focus-visible:bg-raised"
      >
        {/* biome-ignore lint/a11y/useKeyWithClickEvents: stopPropagation wrapper, the inner Toggle handles its own keyboard events */}
        {/* biome-ignore lint/a11y/noStaticElementInteractions: click-swallow wrapper isolates the Toggle from the row's expand handler */}
        <div onClick={(e) => e.stopPropagation()}>
          <Toggle checked={checked} onChange={onToggle} label={toggleLabel} />
        </div>
        {leadingChips}
        {isModified && <span className="h-1 w-1 shrink-0 rounded-full bg-amber" />}
        <span className="flex-1 min-w-0 truncate text-[13px] leading-5 text-txt-2">{preview}</span>
        {size}
      </div>
      {children}
    </div>
  );
}

export const inputClass =
  "w-full min-h-24 resize-none field-sizing-content bg-canvas px-3 py-2 text-[13px] text-txt border border-edge focus:border-accent/50 focus:outline-none transition-colors font-mono";

// Tone class for a size-delta number based on direction of change.
// Sage ("you cut it down") for shrinks, amber ("it grew") for growths,
// keyed off the same amber the edit dot uses so the palette stays tight.
// Exposed separately so non-component callers can tone other numbers
// (e.g. token counts) the same way without importing the JSX.
export function sizeDeltaTone(original: number, current: number): string {
  if (current < original) return "text-sage";
  if (current > original) return "text-amber";
  return "text-txt-3";
}

// Right-edge size label shared across the Breakpoint editor rows.
// Renders ``{original}[ → {current}] {suffix}`` with the current count
// tinted by :func:`sizeDeltaTone` when it differs from original. Keeps
// the same ``label shrink-0`` chrome as the raw number so callers can
// swap in-place.
export function SizeDelta({
  original,
  current,
  suffix = "chars",
}: {
  original: number;
  current: number;
  suffix?: string;
}) {
  const changed = current !== original;
  const toneClass = sizeDeltaTone(original, current);
  return (
    <span className="label shrink-0 text-txt-3 metric-num">
      {original.toLocaleString()}
      {changed && (
        <>
          {" \u2192 "}
          <span className={toneClass}>{current.toLocaleString()}</span>
        </>
      )}
      {suffix ? ` ${suffix}` : ""}
    </span>
  );
}
