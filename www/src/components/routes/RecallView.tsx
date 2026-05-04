import { TransportMattersIcon } from "../TransportMattersIcon";

/**
 * RECALL — project session browser.
 *
 * Placeholder. Mirrors the entry-page atmosphere: a giant faded Transport Matters
 * silhouette ticking in the background, centered foreground copy. The
 * route reads as "waiting for the next version", in the same visual voice
 * as "waiting for exchanges" on the entry page. Accent: sky.
 */
export function RecallView() {
  return (
    <div className="relative h-full overflow-hidden">
      {/* Atmospheric backdrop — identical treatment to the entry page's
          faded, ticking silhouette. The icon extends beyond the panel;
          overflow-hidden trims it. */}
      <div
        aria-hidden
        className="absolute inset-0 flex items-center justify-center text-edge-subtle opacity-30 pointer-events-none"
      >
        <TransportMattersIcon className="spin-gentle h-[90vh] w-[90vh]" />
      </div>

      {/* Centered foreground stack */}
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-7 px-8 text-center">
        <div className="flex flex-col items-center gap-4">
          <TransportMattersIcon className="h-[64px] w-[64px] text-txt shrink-0" />
          <h2 className="text-[18px] font-semibold tracking-[0.22em] text-txt uppercase">Recall</h2>
          <span className="label text-[12px]">Session browser</span>
        </div>
        <p className="max-w-[500px] text-[14px] leading-[1.7] text-txt-3">
          Discover what happened in prior Claude Code sessions. Search across captured exchanges,
          replay with or without saved overlays, and surface context that would otherwise stay
          buried in a week-old session log.
        </p>
        <div className="flex items-center gap-2 text-[12px] uppercase tracking-[0.22em] text-sky">
          <span aria-hidden className="h-1 w-1 rounded-full bg-sky" />
          <span>Coming soon</span>
        </div>
      </div>
    </div>
  );
}
