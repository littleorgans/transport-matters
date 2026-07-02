import { type ReactNode, useState } from "react";
import { hasDismissedPanel, markPanelDismissed } from "../../stores/persistence";

type Tone = "warn" | "info";

// Each tone carries a 3px left accent rail (matching the PAUSED marker
// idiom from PausedHeader), a low-alpha wash, a hairline border, and a
// tone-colored title. Warn reserves rose — the palette's red — for
// panels flagging that user action has provider-visible consequences.
// Info takes sky so the reader registers it as explanatory reference
// (distinct from amber, which is live-state / caution). Amber stays
// unused here so those two state families don't collide.
const TONES: Record<Tone, { rail: string; border: string; bg: string; label: string }> = {
  warn: {
    rail: "bg-rose/70",
    border: "border-rose/25",
    bg: "bg-rose/[0.04]",
    label: "text-rose",
  },
  info: {
    rail: "bg-sky/60",
    border: "border-sky/20",
    bg: "bg-sky/[0.03]",
    label: "text-sky",
  },
};

interface DismissablePanelProps {
  id: string;
  tone: Tone;
  title: string;
  children: ReactNode;
}

export function DismissablePanel({ id, tone, title, children }: DismissablePanelProps) {
  // Seed from localStorage on mount. No reactivity needed: dismissal
  // is a one-way transition, and cross-tab sync isn't worth the
  // listener complexity for a first-run notice.
  const [dismissed, setDismissed] = useState(() => hasDismissedPanel(id));
  if (dismissed) return null;

  const styles = TONES[tone];
  const handleDismiss = () => {
    markPanelDismissed(id);
    setDismissed(true);
  };

  return (
    <div
      className={`relative mx-5 mt-3 border ${styles.border} ${styles.bg} pl-5 pr-9 py-3 text-[13px] text-txt-2`}
    >
      {/* Left accent rail — same idiom as the PAUSED marker in PausedHeader,
          borrowed so the advisory panel reads as a marked region of the
          layout rather than a generic card. Rides above the tone border
          on the left edge. */}
      <span className={`absolute left-0 top-0 bottom-0 w-[3px] ${styles.rail}`} aria-hidden />
      <button
        type="button"
        onClick={handleDismiss}
        aria-label={`Dismiss ${title}`}
        className="absolute right-2 top-2 cursor-pointer p-1 text-txt-3 transition-colors hover:text-txt"
      >
        {/* Hand-rolled × glyph. 12px keeps the hit target small so the
            dismiss doesn't read as an action button. Same stroke weight
            as the arrow glyphs used elsewhere in the editor. */}
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
          <path
            d="M2 2 L10 10 M10 2 L2 10"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </svg>
      </button>
      <div className={`label mb-1 ${styles.label}`}>{title}</div>
      <div className="leading-relaxed">{children}</div>
    </div>
  );
}
