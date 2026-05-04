import { TransportMattersIcon } from "../TransportMattersIcon";

/**
 * TRACE — non-interactive topological view of the exchange stream.
 *
 * Placeholder. Mirrors the entry-page atmosphere: a giant faded Transport Matters
 * silhouette ticking in the background, centered foreground copy. The
 * route reads as "waiting for the next version", in the same visual voice
 * as "waiting for exchanges" on the entry page. Accent: lavender.
 */
export function TraceView() {
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
          <h2 className="text-[18px] font-semibold tracking-[0.22em] text-txt uppercase">Trace</h2>
          <span className="label text-[12px]">Topology view</span>
        </div>
        <p className="max-w-[500px] text-[14px] leading-[1.7] text-txt-3">
          A non-interactive diagram of every exchange in this session, the overlays that shaped each
          one, and the paths the provider took in response.
        </p>
        <div className="flex items-center gap-2 text-[12px] uppercase tracking-[0.22em] text-lavender">
          <span aria-hidden className="h-1 w-1 rounded-full bg-lavender" />
          <span>Coming soon</span>
        </div>
      </div>
    </div>
  );
}
