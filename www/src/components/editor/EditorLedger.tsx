import { useState } from "react";
import type { InternalRequest } from "../../types";
import { HoverCard } from "../HoverCard";
import { Toggle } from "../Toggle";

export interface OverridesFooterProps {
  storedCount: number;
  appliedCount: number;
  enabled: boolean;
  onToggle: () => void;
  onClear: () => void;
}

export interface CharBreakdown {
  system: number;
  tools: number;
  messages: number;
  total: number;
}

export function countCharsParts(ir: InternalRequest): CharBreakdown {
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

type CategoryKey = "system" | "tools" | "messages";

const CATEGORY: Record<CategoryKey, { bg: string; tick: string; text: string }> = {
  system: { bg: "bg-lavender/70", tick: "bg-lavender", text: "text-lavender" },
  tools: { bg: "bg-teal/70", tick: "bg-teal", text: "text-teal" },
  messages: { bg: "bg-amber/70", tick: "bg-amber", text: "text-amber" },
};

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

interface LedgerViewProps {
  before: CharBreakdown;
  after: CharBreakdown;
  beforeSegments: LedgerSegment[];
  afterSegments: LedgerSegment[];
  delta: number;
  hasDelta: boolean;
  maxTotal: number;
  deltaPct: number;
}

function CollapsedCharsLedger({
  before,
  after,
  afterSegments,
  delta,
  hasDelta,
  maxTotal,
  deltaPct,
  onExpand,
}: LedgerViewProps & { onExpand: () => void }) {
  return (
    <button
      type="button"
      onClick={onExpand}
      className="group flex w-full cursor-pointer items-center gap-6 px-6 py-3 text-left transition-colors hover:bg-raised"
    >
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

function ExpandedCharsLedger({
  before,
  after,
  beforeSegments,
  afterSegments,
  delta,
  hasDelta,
  maxTotal,
  deltaPct,
  onCollapse,
}: LedgerViewProps & { onCollapse: () => void }) {
  return (
    // biome-ignore lint/a11y/useSemanticElements: this collapse affordance wraps block-level ledger layout and HoverCard divs
    <div
      role="button"
      tabIndex={0}
      onClick={onCollapse}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onCollapse();
        }
      }}
      className="relative flex cursor-pointer items-start gap-8 px-8 py-5 transition-colors hover:bg-raised/40 focus:outline-none focus-visible:bg-raised/40"
    >
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
        <div className="space-y-1.5">
          <LedgerItem
            categoryKey="system"
            label="system"
            before={before.system}
            after={after.system}
          />
          <LedgerItem categoryKey="tools" label="tools" before={before.tools} after={after.tools} />
          <LedgerItem
            categoryKey="messages"
            label="messages"
            before={before.messages}
            after={after.messages}
          />
        </div>
      </div>
    </div>
  );
}

function buildSegments(chars: CharBreakdown): LedgerSegment[] {
  return [
    { key: "system", label: "system", value: chars.system },
    { key: "tools", label: "tools", value: chars.tools },
    { key: "messages", label: "messages", value: chars.messages },
  ];
}

export function CharsLedger({ before, after, overridesFooter }: CharsLedgerProps) {
  const [expanded, setExpanded] = useState(false);
  const delta = after.total - before.total;
  const hasDelta = delta !== 0;
  const maxTotal = Math.max(before.total, after.total, 1);
  const deltaPct = before.total > 0 ? Math.round((Math.abs(delta) / before.total) * 100) : 0;
  const viewProps: LedgerViewProps = {
    before,
    after,
    beforeSegments: buildSegments(before),
    afterSegments: buildSegments(after),
    delta,
    hasDelta,
    maxTotal,
    deltaPct,
  };

  return (
    <>
      {expanded ? (
        <ExpandedCharsLedger {...viewProps} onCollapse={() => setExpanded(false)} />
      ) : (
        <CollapsedCharsLedger {...viewProps} onExpand={() => setExpanded(true)} />
      )}
      {expanded && overridesFooter && overridesFooter.storedCount > 0 && (
        <>
          <div className="hairline-x" />
          <OverridesFooter {...overridesFooter} />
        </>
      )}
    </>
  );
}
