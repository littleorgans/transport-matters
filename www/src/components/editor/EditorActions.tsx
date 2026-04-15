import { useState } from "react";
import type { InternalRequest, OverrideAudit } from "../../types";
import { HoverCard } from "../HoverCard";
import { Toggle } from "../Toggle";

interface EditorActionsProps {
  originalIr: InternalRequest;
  audit: OverrideAudit | null;
  editedIr: InternalRequest;
  overridesCount: number;
  overridesEnabled: boolean;
  onToggleOverrides: () => void;
  onClearOverrides: () => void;
  onForward: () => void;
  onForwardUnmodified: () => void;
  onDrop: () => void;
  loading: boolean;
}

interface OverridesFooterProps {
  storedCount: number;
  appliedCount: number;
  enabled: boolean;
  onToggle: () => void;
  onClear: () => void;
}

interface CharBreakdown {
  system: number;
  tools: number;
  messages: number;
  total: number;
}

function countCharsParts(ir: InternalRequest): CharBreakdown {
  const system = ir.system.reduce((sum, p) => sum + p.text.length, 0);
  const tools = ir.tools.reduce(
    (sum, t) => sum + t.name.length + t.description.length + JSON.stringify(t.input_schema).length,
    0,
  );
  let messages = 0;
  for (const msg of ir.messages) {
    for (const block of msg.content) {
      messages += JSON.stringify(block).length;
    }
  }
  return { system, tools, messages, total: system + tools + messages };
}

function formatChars(n: number): string {
  if (n >= 10_000) return `${(n / 1000).toFixed(1)}K`;
  return n.toLocaleString();
}

// Category palette — one pastel per content source. Bars, ticks, and
// hover-card labels all pull from this table so the visual language
// stays coherent from strip to strip. Cool → cool → warm so tools
// and messages don't get read as a single blue-green band.
type CategoryKey = "system" | "tools" | "messages";

const CATEGORY: Record<CategoryKey, { bg: string; tick: string; text: string }> = {
  system: { bg: "bg-lavender/70", tick: "bg-lavender", text: "text-lavender" },
  tools: { bg: "bg-teal/70", tick: "bg-teal", text: "text-teal" },
  messages: { bg: "bg-amber/70", tick: "bg-amber", text: "text-amber" },
};

function Spinner() {
  return (
    <span className="inline-block h-3 w-3 rounded-full border-2 border-current/30 border-t-current spinner" />
  );
}

interface LedgerSegment {
  key: CategoryKey;
  label: string;
  value: number;
}

function LedgerRow({
  label,
  total,
  maxTotal,
  segments,
  savedAmount,
  savedPct,
}: {
  label: string;
  total: number;
  maxTotal: number;
  segments: LedgerSegment[];
  savedAmount?: number;
  savedPct?: number;
}) {
  const hasGap = savedAmount !== undefined && savedAmount > 0;
  return (
    <div className="flex items-center gap-3">
      <span className="label w-14 shrink-0">{label}</span>
      <div className="bar-track relative flex h-3 flex-1 overflow-hidden bg-canvas">
        {segments.map((s) => {
          const segPct = (s.value / maxTotal) * 100;
          if (segPct <= 0) return null;
          const style = CATEGORY[s.key];
          return (
            <HoverCard
              key={s.key}
              content={
                <span>
                  <span className={style.text}>{s.label}</span> {formatChars(s.value)}
                </span>
              }
            >
              <div className={`h-full ${style.bg}`} style={{ width: `${segPct}%` }} />
            </HoverCard>
          );
        })}
        {hasGap && (
          <HoverCard
            content={
              <span>
                <span className="text-sage">saved</span> {formatChars(savedAmount)} ({savedPct}%)
              </span>
            }
          >
            <div className="h-full flex-1 border-l border-dashed border-sage/40 bg-sage/[0.04]" />
          </HoverCard>
        )}
      </div>
      <span className="metric-num w-[72px] shrink-0 text-right text-[14px] text-txt tabular-nums">
        {formatChars(total)}
      </span>
    </div>
  );
}

function LedgerItem({
  categoryKey,
  label,
  before,
  after,
}: {
  categoryKey: CategoryKey;
  label: string;
  before: number;
  after: number;
}) {
  const delta = after - before;
  const pct = before > 0 ? Math.round((Math.abs(delta) / before) * 100) : 0;
  const noChange = delta === 0;
  const tick = CATEGORY[categoryKey].tick;
  return (
    <div className="flex items-baseline gap-2 whitespace-nowrap">
      <span className={`inline-block h-3 w-[2px] self-center ${tick}`} />
      <span className="label">{label}</span>
      {noChange ? (
        <span className="metric-num text-[13px] text-txt">{formatChars(before)}</span>
      ) : (
        <>
          <span className="metric-num text-[13px] text-txt-3">{formatChars(before)}</span>
          <span className="text-[11px] text-txt-3">&rarr;</span>
          <span className="metric-num text-[13px] text-txt">{formatChars(after)}</span>
          <span className={`metric-num text-[12px] ${delta < 0 ? "text-sage" : "text-amber"}`}>
            {delta < 0 ? "\u2212" : "+"}
            {pct}%
          </span>
        </>
      )}
    </div>
  );
}

// Overrides footer — the expanded ledger's caption strip. Lives below
// the savings story as its source/provenance: "these N overrides are
// why the bar shortened." Horizontal rhythm intentionally mirrors the
// action-strip above (px-8 gutter, quiet label → control → count →
// right-anchored action) so the whole panel reads as one vertical system
// rather than disconnected parts. Sits outside the collapsible body so
// the Toggle/Clear controls don't fold the ledger when clicked.
function OverridesFooter({
  storedCount,
  appliedCount,
  enabled,
  onToggle,
  onClear,
}: OverridesFooterProps) {
  const allApplied = appliedCount === storedCount;
  const [confirmClear, setConfirmClear] = useState(false);

  const handleClear = () => {
    if (!confirmClear) {
      setConfirmClear(true);
      setTimeout(() => setConfirmClear(false), 3000);
      return;
    }
    setConfirmClear(false);
    onClear();
  };

  return (
    <div className="flex items-center gap-4 px-8 py-3">
      <span className="label">Overrides</span>
      <Toggle checked={enabled} onChange={onToggle} label="Toggle overrides" size="sm" />
      {/* Count reads as prose — numbers in bone, connective words dimmed.
          Dim the whole line when disabled so the state and the text
          agree visually without redundant "bypassed" prose. */}
      <span
        className={`metric-num text-[13px] whitespace-nowrap transition-opacity ${
          enabled ? "" : "opacity-55"
        }`}
      >
        {allApplied ? (
          <span className="text-txt">
            {storedCount} override{storedCount !== 1 ? "s" : ""}
          </span>
        ) : (
          <>
            <span className="text-txt">{storedCount}</span>
            <span className="text-txt-3"> stored &middot; </span>
            <span className="text-txt">{appliedCount}</span>
            <span className="text-txt-3"> applied</span>
          </>
        )}
      </span>
      <div className="flex-1" />
      {/* CLEAR — tertiary destructive action. Same rose language as the
          primary Drop button (intent legible at a glance) but a half-step
          scaled down so it reads as a sub-action in this caption strip.
          Confirmation state fills in more strongly to commit the user. */}
      <button
        type="button"
        onClick={handleClear}
        className={`cursor-pointer border px-3 py-1 text-[10px] font-medium uppercase tracking-[0.14em] transition-colors ${
          confirmClear
            ? "border-rose/60 bg-rose/15 text-rose"
            : "border-rose/25 bg-rose/5 text-rose/80 hover:bg-rose/12 hover:text-rose"
        }`}
      >
        {confirmClear ? "Confirm" : "Clear"}
      </button>
    </div>
  );
}

interface CharsLedgerProps {
  before: CharBreakdown;
  after: CharBreakdown;
  overridesFooter?: OverridesFooterProps;
}

// Named for the unit it actually measures — characters, not tokens.
// The real token readout lives in PausedHeader as a count_tokens-backed
// chip; this ledger is the local diff story (what overrides took out of
// the IR) and characters are the honest unit for a structural edit.
function CharsLedger({ before, after, overridesFooter }: CharsLedgerProps) {
  const [expanded, setExpanded] = useState(false);
  const delta = after.total - before.total;
  const hasDelta = delta !== 0;
  const maxTotal = Math.max(before.total, after.total, 1);
  const deltaPct = before.total > 0 ? Math.round((Math.abs(delta) / before.total) * 100) : 0;

  const beforeSegments: LedgerSegment[] = [
    { key: "system", label: "system", value: before.system },
    { key: "tools", label: "tools", value: before.tools },
    { key: "messages", label: "messages", value: before.messages },
  ];
  const afterSegments: LedgerSegment[] = [
    { key: "system", label: "system", value: after.system },
    { key: "tools", label: "tools", value: after.tools },
    { key: "messages", label: "messages", value: after.messages },
  ];

  // Collapsed — single clickable strip conveying the savings story
  // on one row: SAVED delta on the left, an after-composition bar
  // with a dashed savings trail, before → after totals on the right.
  // The whole strip is the affordance; hover lightens the row so
  // there's no need for an explicit "expand" label cluttering the end.
  if (!expanded) {
    return (
      <button
        type="button"
        onClick={() => setExpanded(true)}
        className="group flex w-full cursor-pointer items-center gap-6 px-6 py-3 text-left transition-colors hover:bg-raised"
      >
        {/* Delta chip — pill analogue of the expanded disc. Same tint
            semantic (sage savings / amber spend), same bone-neutral
            glyphs, scaled down to a rounded-full badge that sits on the
            strip like a stamped token. The pill's `rounded-full` echoes
            the circular disc so the two states read as one visual
            language at different scales. */}
        <div
          className={`flex shrink-0 items-baseline gap-2 whitespace-nowrap metric-num tabular-nums px-3 py-1 ${
            hasDelta
              ? delta < 0
                ? "bg-sage/20 ring-1 ring-sage/30"
                : "bg-amber/20 ring-1 ring-amber/30"
              : ""
          }`}
        >
          <span className="label">{hasDelta ? "Saved" : "Budget"}</span>
          {hasDelta ? (
            <>
              <span className="text-[16px] leading-none text-txt">
                {delta < 0 ? "\u2212" : "+"}
                {formatChars(Math.abs(delta))}
              </span>
              <span className="text-[12px] leading-none text-txt-2">
                {delta < 0 ? "\u2212" : "+"}
                {deltaPct}%
              </span>
            </>
          ) : (
            <span className="text-[16px] leading-none text-txt">{formatChars(before.total)}</span>
          )}
        </div>

        <div className="bar-track relative flex h-2 min-w-0 flex-1 overflow-hidden bg-canvas">
          {afterSegments.map((s) => {
            const pct = (s.value / maxTotal) * 100;
            if (pct <= 0) return null;
            return (
              <div
                key={s.key}
                className={`h-full ${CATEGORY[s.key].bg}`}
                style={{ width: `${pct}%` }}
              />
            );
          })}
          {hasDelta && delta < 0 && (
            <div className="h-full flex-1 border-l border-dashed border-sage/40 bg-sage/[0.04]" />
          )}
        </div>

        <div className="flex shrink-0 items-baseline gap-2 whitespace-nowrap metric-num tabular-nums text-[12px]">
          <span className="text-txt-3">{formatChars(before.total)}</span>
          <span className="text-txt-3">&rarr;</span>
          <span className="text-txt-2">{formatChars(after.total)}</span>
        </div>
      </button>
    );
  }

  // Expanded — the full ledger. The main body is the collapse
  // affordance: clicking anywhere inside it folds back to the one-row
  // strip. HoverCards inside are non-interactive divs with mouse
  // handlers, so they bubble their clicks up to this handler without
  // conflict. The overrides footer sits as a sibling beneath a hairline
  // so its Toggle/Clear controls can be interacted with without
  // collapsing the ledger.
  return (
    <>
      {/* biome-ignore lint/a11y/useSemanticElements: collapse affordance wraps block-level ledger layout (HoverCard divs); a native button cannot host that content */}
      <div
        role="button"
        tabIndex={0}
        onClick={() => setExpanded(false)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setExpanded(false);
          }
        }}
        className="relative flex cursor-pointer items-start gap-8 px-8 py-5 transition-colors hover:bg-raised/40 focus:outline-none focus-visible:bg-raised/40"
      >
        {/* Hero — instrument-dial treatment. A circular ::after disc sits
          centered behind the content, carrying the savings/spend
          semantic as a colored coin rather than a rectangular fill. The
          parent `isolate` pins the stacking context so the disc's
          `-z-10` falls behind the cell's own content without sinking
          through the strip. Numbers stay bone-weight; the disc does the
          emotional work, like a painted indicator on a mixing desk. */}
        <div
          className={`relative isolate flex w-[132px] shrink-0 flex-col items-center justify-center gap-2 self-stretch text-center
          after:pointer-events-none after:absolute after:left-1/2 after:top-1/2
          after:h-[116px] after:w-[116px] after:-translate-x-1/2 after:-translate-y-1/2
          after:rounded-full after:content-[''] after:-z-10 ${
            hasDelta
              ? delta < 0
                ? "after:bg-sage/20 after:ring-1 after:ring-sage/30"
                : "after:bg-amber/20 after:ring-1 after:ring-amber/30"
              : ""
          }`}
        >
          <span className="label">{hasDelta ? "Saved" : "Budget"}</span>
          <div className="metric-num space-y-1 leading-none whitespace-nowrap tabular-nums text-txt">
            {hasDelta ? (
              <>
                <div className="text-[22px]">
                  {delta < 0 ? "\u2212" : "+"}
                  {formatChars(Math.abs(delta))}
                </div>
                <div className="text-[13px] text-txt-2">
                  {delta < 0 ? "\u2212" : "+"}
                  {deltaPct}%
                </div>
              </>
            ) : (
              <span className="text-[22px]">{formatChars(before.total)}</span>
            )}
          </div>
        </div>

        {/* Ledger — two stacked bars on the same scale so the
          shortening of the "after" bar IS the visual story of the
          savings. The trailing dashed region marks what was removed. */}
        <div className="min-w-0 flex-1 space-y-3">
          <div className="space-y-2">
            <LedgerRow
              label="before"
              total={before.total}
              maxTotal={maxTotal}
              segments={beforeSegments}
            />
            {hasDelta && (
              <LedgerRow
                label="after"
                total={after.total}
                maxTotal={maxTotal}
                segments={afterSegments}
                savedAmount={Math.abs(delta)}
                savedPct={deltaPct}
              />
            )}
          </div>
          {/* Per-category ledger — one row per content source so the
            eye can scan vertically through the diff. Stacking removes
            any risk of wrap when numbers grow, and mirrors the
            before/after bar rhythm above it (one row = one fact). */}
          <div className="space-y-1.5">
            <LedgerItem
              categoryKey="system"
              label="system"
              before={before.system}
              after={after.system}
            />
            <LedgerItem
              categoryKey="tools"
              label="tools"
              before={before.tools}
              after={after.tools}
            />
            <LedgerItem
              categoryKey="messages"
              label="messages"
              before={before.messages}
              after={after.messages}
            />
          </div>
        </div>
      </div>
      {overridesFooter && overridesFooter.storedCount > 0 && (
        <>
          <div className="hairline-x" />
          <OverridesFooter {...overridesFooter} />
        </>
      )}
    </>
  );
}

export function EditorActions({
  originalIr,
  audit,
  editedIr,
  overridesCount,
  overridesEnabled,
  onToggleOverrides,
  onClearOverrides,
  onForward,
  onForwardUnmodified,
  onDrop,
  loading,
}: EditorActionsProps) {
  const fallback = countCharsParts(originalIr);
  const fallbackAfter = countCharsParts(editedIr);

  const before: CharBreakdown = audit
    ? {
        system: audit.system_chars_before,
        tools: audit.tools_chars_before,
        messages: audit.messages_chars_before,
        total: audit.chars_before,
      }
    : fallback;

  const after: CharBreakdown = audit
    ? {
        system: audit.system_chars_after,
        tools: audit.tools_chars_after,
        messages: audit.messages_chars_after,
        total: audit.chars_after,
      }
    : fallbackAfter;

  const appliedCount = audit?.entries.filter((e) => e.applied).length ?? 0;
  const storedCount = overridesCount;

  // Consistent button geometry: same padding, min-width, typography.
  // Tone differentiates role (rose=destructive, neutral=pass-through,
  // accent=primary forward) without breaking the cluster's rhythm.
  const btnBase =
    "btn cursor-pointer border px-4 py-2 text-[12px] font-medium uppercase tracking-[0.14em] min-w-[110px] whitespace-nowrap transition-colors";

  return (
    <div className="top-highlight bg-surface">
      {/* Strip 1 — request-lifecycle cluster. Drop / Pass Through /
          Forward are the three terminal verdicts on a paused flow and
          live right-anchored so the eye lands on them at rest. SAVE AS
          OVERLAY is no longer in this strip — it now lives inside the
          OVERLAY tab where it reads as the commit action for the
          durable session shape that tab shows. */}
      <div className="flex items-center justify-end gap-2 px-6 py-2">
        <button
          type="button"
          disabled={loading}
          onClick={onDrop}
          className={`${btnBase} border-rose/25 bg-rose/5 text-rose hover:bg-rose/10`}
        >
          {loading ? <Spinner /> : "Drop"}
        </button>
        <button
          type="button"
          disabled={loading}
          onClick={onForwardUnmodified}
          className={`${btnBase} border-edge bg-surface text-txt-2 hover:bg-raised hover:text-txt`}
        >
          {loading ? <Spinner /> : "Pass Through"}
        </button>
        <button
          type="button"
          disabled={loading}
          onClick={onForward}
          className={`${btnBase} border-accent/30 bg-accent/8 text-accent hover:bg-accent/15`}
        >
          {loading ? <Spinner /> : "Forward"}
        </button>
      </div>

      <div className="hairline-x" />

      {/* Strip 2 — chars ledger. Headline savings hero on the left,
          two-row before/after segmented bar on the right, per-category
          diff readout below. Unit is characters (what overrides
          physically remove from the IR); the tokens story lives in the
          PausedHeader chip. When expanded and overrides are present,
          an OVERRIDES footer strip appears beneath the ledger as the
          caption/provenance for the savings shown above it. */}
      <CharsLedger
        before={before}
        after={after}
        overridesFooter={{
          storedCount,
          appliedCount,
          enabled: overridesEnabled,
          onToggle: onToggleOverrides,
          onClear: onClearOverrides,
        }}
      />

      <div className="hairline-x" />
    </div>
  );
}
