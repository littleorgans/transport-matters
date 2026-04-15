import { useEffect, useRef, useState } from "react";
import { hasOverride } from "../../lib/overrides";
import type { Override, SamplingParams } from "../../types";
import { HelpBubble } from "../HelpBubble";

/**
 * SAMPLING section. All edits flow through the override pipeline as
 * ``sampling_set`` and ``provider_extras_set`` so the audit ledger tracks
 * knob edits alongside content edits and the "Save as overlay" action
 * captures them durably.
 *
 * Values ride on ``Override.value`` as JSON-encoded strings so a scalar
 * ``str | bool | int | null`` union can carry floats, lists, and objects
 * without widening the Override schema — the backend parses on apply.
 * Dotted-path targets (``provider_extras:thinking.display``,
 * ``provider_extras:output_config.effort``) let DISPLAY and EFFORT land
 * at specific nested keys without clobbering siblings.
 *
 * Fields commit on blur rather than per-keystroke so each logical edit
 * emits one override (not N) and the network side stays quiet while the
 * user is typing.
 */

type ThinkingMode = "off" | "adaptive" | "enabled";
type DisplayMode = "summarized" | "omitted";
type EffortLevel = "low" | "medium" | "high" | "max";

interface SamplingSectionProps {
  sampling: SamplingParams;
  /**
   * Pristine sampling from the paused flow's ``original_ir`` — used to
   * decide "commit clears the override" when the user edits back to the
   * source value, so the ledger doesn't carry redundant no-op entries.
   */
  originalSampling: SamplingParams;
  providerExtras: Record<string, unknown>;
  originalProviderExtras: Record<string, unknown>;
  overrides: Override[];
  onOverride: (batch: Override[]) => void;
}

const inputClass =
  "w-full bg-canvas border border-edge px-3 py-2 text-[13px] text-txt focus:border-accent/50 focus:outline-none transition-colors metric-num";

const labelClass = "label flex items-center";

const THINKING_TARGET = "provider_extras:thinking";
const DISPLAY_TARGET = "provider_extras:thinking.display";
const EFFORT_TARGET = "provider_extras:output_config.effort";

const SAMPLING_TARGETS: Record<keyof SamplingParams, string> = {
  max_tokens: "sampling:max_tokens",
  temperature: "sampling:temperature",
  top_p: "sampling:top_p",
  top_k: "sampling:top_k",
  stop_sequences: "sampling:stop_sequences",
};

const MIN_BUDGET = 1024;
const DEFAULT_BUDGET = 10000;

// ─── Provider-extras readers ────────────────────────────────────────

function readThinkingDict(extras: Record<string, unknown>): Record<string, unknown> | null {
  const t = extras.thinking;
  if (!t || typeof t !== "object") return null;
  return t as Record<string, unknown>;
}

function getThinkingMode(extras: Record<string, unknown>): ThinkingMode {
  const t = readThinkingDict(extras);
  if (!t) return "off";
  if (t.type === "adaptive") return "adaptive";
  if (t.type === "enabled") return "enabled";
  return "off";
}

function getBudget(extras: Record<string, unknown>): number {
  const t = readThinkingDict(extras);
  if (t && typeof t.budget_tokens === "number") return t.budget_tokens;
  return DEFAULT_BUDGET;
}

function getDisplay(extras: Record<string, unknown>): DisplayMode {
  const t = readThinkingDict(extras);
  if (t && t.display === "omitted") return "omitted";
  return "summarized"; // default (absent key == summarized in the Anthropic API)
}

function getEffort(extras: Record<string, unknown>): EffortLevel | null {
  const oc = extras.output_config;
  if (!oc || typeof oc !== "object") return null;
  const e = (oc as Record<string, unknown>).effort;
  if (e === "low" || e === "medium" || e === "high" || e === "max") return e;
  return null;
}

// ─── Value equality helpers ─────────────────────────────────────────

function stopSeqsEqual(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

function samplingValuesEqual<K extends keyof SamplingParams>(
  field: K,
  a: SamplingParams[K],
  b: SamplingParams[K],
): boolean {
  if (field === "stop_sequences") {
    return stopSeqsEqual(a as string[], b as string[]);
  }
  return a === b;
}

function buildCommit<K extends keyof SamplingParams>(
  field: K,
  newValue: SamplingParams[K],
  originalValue: SamplingParams[K],
): Override {
  const target = SAMPLING_TARGETS[field];
  if (samplingValuesEqual(field, newValue, originalValue)) {
    // Edited back to the source value — clear the override rather than
    // record a no-op entry in the audit.
    return { kind: "sampling_set", target, value: null };
  }
  return { kind: "sampling_set", target, value: JSON.stringify(newValue) };
}

// ─── Segmented-track atom ───────────────────────────────────────────
// Zero-radius, 1px dividers, sage-wash for the active segment. Used by
// THINKING, DISPLAY, and EFFORT. Inline because all three call sites
// live in this module; promote to its own file if a fourth surface
// needs the pattern.

interface SegmentOption<T extends string> {
  label: string;
  value: T;
}

interface SegmentedTrackProps<T extends string> {
  value: T;
  options: readonly SegmentOption<T>[];
  onChange: (value: T) => void;
  disabled?: boolean;
  ariaLabel: string;
}

function SegmentedTrack<T extends string>({
  value,
  options,
  onChange,
  disabled = false,
  ariaLabel,
}: SegmentedTrackProps<T>) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={`flex border border-edge bg-canvas divide-x divide-edge ${
        disabled ? "opacity-40 pointer-events-none" : ""
      }`}
    >
      {options.map((opt) => {
        const selected = opt.value === value;
        return (
          <button
            key={opt.value}
            type="button"
            role="tab"
            aria-selected={selected}
            disabled={disabled}
            onClick={() => onChange(opt.value)}
            className={`flex-1 px-3 py-1.5 uppercase text-[11px] tracking-[0.2em] cursor-pointer transition-colors ${
              selected ? "bg-sage/15 text-txt" : "text-txt-3 hover:text-txt-2"
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

// ─── Section component ──────────────────────────────────────────────

export function SamplingSection({
  sampling,
  originalSampling,
  providerExtras,
  originalProviderExtras,
  overrides,
  onOverride,
}: SamplingSectionProps) {
  const [localMaxTokens, setLocalMaxTokens] = useState(String(sampling.max_tokens));
  const [localTemp, setLocalTemp] = useState(
    sampling.temperature == null ? "" : String(sampling.temperature),
  );
  const [localTopP, setLocalTopP] = useState(sampling.top_p == null ? "" : String(sampling.top_p));
  const [localTopK, setLocalTopK] = useState(sampling.top_k == null ? "" : String(sampling.top_k));
  const [localStopSeqs, setLocalStopSeqs] = useState(sampling.stop_sequences.join(", "));

  useEffect(() => {
    setLocalMaxTokens(String(sampling.max_tokens));
  }, [sampling.max_tokens]);
  useEffect(() => {
    setLocalTemp(sampling.temperature == null ? "" : String(sampling.temperature));
  }, [sampling.temperature]);
  useEffect(() => {
    setLocalTopP(sampling.top_p == null ? "" : String(sampling.top_p));
  }, [sampling.top_p]);
  useEffect(() => {
    setLocalTopK(sampling.top_k == null ? "" : String(sampling.top_k));
  }, [sampling.top_k]);
  useEffect(() => {
    setLocalStopSeqs(sampling.stop_sequences.join(", "));
  }, [sampling.stop_sequences]);

  const thinkingMode = getThinkingMode(providerExtras);
  const budget = getBudget(providerExtras);
  const display = getDisplay(providerExtras);
  const effort = getEffort(providerExtras);

  const thinkingActive = thinkingMode !== "off";
  const budgetEnabled = thinkingMode === "enabled";

  // Remember the last real budget so turning thinking back to enabled
  // restores whatever the user had configured, not a hard-coded default.
  const budgetRef = useRef(budget);
  if (budgetEnabled) budgetRef.current = budget;

  const [localBudget, setLocalBudget] = useState(String(budget));
  useEffect(() => {
    setLocalBudget(String(budget));
  }, [budget]);

  const isFieldModified = (field: keyof SamplingParams): boolean =>
    hasOverride(overrides, "sampling_set", SAMPLING_TARGETS[field]);
  const thinkingModified = hasOverride(overrides, "provider_extras_set", THINKING_TARGET);
  const displayModified = hasOverride(overrides, "provider_extras_set", DISPLAY_TARGET);
  const effortModified = hasOverride(overrides, "provider_extras_set", EFFORT_TARGET);

  const samplingOverrideCount = overrides.filter(
    (o) => o.kind === "sampling_set" || o.kind === "provider_extras_set",
  ).length;

  const commitMaxTokens = () => {
    const n = Number.parseInt(localMaxTokens, 10);
    if (Number.isNaN(n)) {
      setLocalMaxTokens(String(sampling.max_tokens));
      return;
    }
    onOverride([buildCommit("max_tokens", n, originalSampling.max_tokens)]);
  };

  const commitFloatField = (
    field: "temperature" | "top_p",
    raw: string,
    resetLocal: (v: string) => void,
  ) => {
    if (raw.trim() === "") {
      onOverride([buildCommit(field, null, originalSampling[field])]);
      return;
    }
    const n = Number(raw);
    if (Number.isNaN(n)) {
      resetLocal(sampling[field] == null ? "" : String(sampling[field]));
      return;
    }
    onOverride([buildCommit(field, n, originalSampling[field])]);
  };

  const commitTopK = () => {
    if (localTopK.trim() === "") {
      onOverride([buildCommit("top_k", null, originalSampling.top_k)]);
      return;
    }
    const n = Number(localTopK);
    if (Number.isNaN(n)) {
      setLocalTopK(sampling.top_k == null ? "" : String(sampling.top_k));
      return;
    }
    onOverride([buildCommit("top_k", Math.round(n), originalSampling.top_k)]);
  };

  const commitStopSeqs = () => {
    const seqs = localStopSeqs
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    onOverride([buildCommit("stop_sequences", seqs, originalSampling.stop_sequences)]);
  };

  const commitBudget = () => {
    const n = Number.parseInt(localBudget, 10);
    if (Number.isNaN(n) || n < MIN_BUDGET) {
      // Bounce back to the last good budget; don't emit invalid edits.
      setLocalBudget(String(budget));
      return;
    }
    const originalMode = getThinkingMode(originalProviderExtras);
    const originalBudget = getBudget(originalProviderExtras);
    // Edit back to the pristine enabled-budget pair — clear the override.
    if (originalMode === "enabled" && originalBudget === n) {
      onOverride([{ kind: "provider_extras_set", target: THINKING_TARGET, value: null }]);
      return;
    }
    onOverride([
      {
        kind: "provider_extras_set",
        target: THINKING_TARGET,
        value: JSON.stringify({ type: "enabled", budget_tokens: n }),
      },
    ]);
  };

  const resetField = (field: keyof SamplingParams) => {
    onOverride([{ kind: "sampling_set", target: SAMPLING_TARGETS[field], value: null }]);
  };

  const resetThinking = () => {
    onOverride([{ kind: "provider_extras_set", target: THINKING_TARGET, value: null }]);
  };

  const resetDisplay = () => {
    onOverride([{ kind: "provider_extras_set", target: DISPLAY_TARGET, value: null }]);
  };

  const resetEffort = () => {
    onOverride([{ kind: "provider_extras_set", target: EFFORT_TARGET, value: null }]);
  };

  const changeThinkingMode = (next: ThinkingMode) => {
    if (next === thinkingMode) return;
    const batch: Override[] = [];

    // ── Thinking key itself ──────────────────────────────────────
    if (next === "off") {
      // Clear the thinking key. If the pristine state had thinking, we
      // need an explicit JSON null to force-delete; otherwise clearing
      // the override is enough.
      const originalHadThinking = readThinkingDict(originalProviderExtras) !== null;
      batch.push({
        kind: "provider_extras_set",
        target: THINKING_TARGET,
        value: originalHadThinking ? "null" : null,
      });
      // Any nested display override would re-materialize thinking as a
      // dict with only a display key — clear it so a thinking-off means
      // thinking-off at every depth.
      batch.push({ kind: "provider_extras_set", target: DISPLAY_TARGET, value: null });
    } else if (next === "adaptive") {
      batch.push({
        kind: "provider_extras_set",
        target: THINKING_TARGET,
        value: JSON.stringify({ type: "adaptive" }),
      });
    } else {
      // enabled
      batch.push({
        kind: "provider_extras_set",
        target: THINKING_TARGET,
        value: JSON.stringify({ type: "enabled", budget_tokens: budgetRef.current }),
      });
    }

    // ── Sampling locks (temp/top_k/top_p) ────────────────────────
    // Anthropic rejects explicit sampling knobs while thinking is on.
    // Only touch them when crossing the active/inactive boundary.
    const wasActive = thinkingActive;
    const isActive = next !== "off";
    if (isActive && !wasActive) {
      for (const f of ["temperature", "top_k", "top_p"] as const) {
        const wantsNull = originalSampling[f] === null;
        batch.push({
          kind: "sampling_set",
          target: SAMPLING_TARGETS[f],
          value: wantsNull ? null : "null",
        });
      }
    } else if (!isActive && wasActive) {
      for (const f of ["temperature", "top_k", "top_p"] as const) {
        batch.push({ kind: "sampling_set", target: SAMPLING_TARGETS[f], value: null });
      }
    }

    onOverride(batch);
  };

  const changeDisplay = (next: DisplayMode) => {
    if (next === display) return;
    const originalDisplay = getDisplay(originalProviderExtras);
    if (next === originalDisplay) {
      onOverride([{ kind: "provider_extras_set", target: DISPLAY_TARGET, value: null }]);
      return;
    }
    onOverride([
      {
        kind: "provider_extras_set",
        target: DISPLAY_TARGET,
        value: JSON.stringify(next),
      },
    ]);
  };

  const changeEffort = (next: EffortLevel | "none") => {
    // "none" is the segmented-track label for "—" (unset). We translate
    // internally rather than typing the segment value as null, because
    // the track expects a string value for keyboard/ARIA stability.
    const nextEffort = next === "none" ? null : next;
    if (nextEffort === effort) return;
    const originalEffort = getEffort(originalProviderExtras);
    if (nextEffort === originalEffort) {
      onOverride([{ kind: "provider_extras_set", target: EFFORT_TARGET, value: null }]);
      return;
    }
    // Two-tier null: pristine-had-no-effort + user-wants-none => clear
    // override (handled above); pristine-had-effort + user-wants-none =>
    // explicit JSON null so the nested clear prunes output_config.
    const jsonValue = nextEffort === null ? "null" : JSON.stringify(nextEffort);
    onOverride([{ kind: "provider_extras_set", target: EFFORT_TARGET, value: jsonValue }]);
  };

  const ResetBtn = ({ onClick }: { onClick: () => void }) => (
    <button
      type="button"
      className="label ml-2 cursor-pointer text-txt-3 transition-colors hover:text-amber"
      onClick={onClick}
    >
      reset
    </button>
  );

  // ─── Thinking help copy ───────────────────────────────────────────

  const thinkingHelp = (
    <HelpBubble>
      <p>
        <span className="text-txt-2">OFF</span> No internal reasoning. Fast, direct responses.
      </p>
      <p className="mt-1.5">
        <span className="text-txt-2">ADAPTIVE</span> The model decides when to think based on the
        prompt.
      </p>
      <p className="mt-1.5">
        <span className="text-txt-2">ENABLED</span> Always think. Budget controls the maximum
        thinking tokens.
      </p>
      <p className="mt-2 text-txt-3">
        When thinking is on, temperature/top_k/top_p are locked to defaults.
      </p>
    </HelpBubble>
  );

  return (
    <section className="space-y-4">
      <div className="section-rule">
        <span className="label">Sampling</span>
        {samplingOverrideCount > 0 && (
          <span className="chip text-amber ml-2">
            {samplingOverrideCount} override{samplingOverrideCount !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      {/* Row 1: MAX TOKENS + STOP SEQUENCES */}
      <div className="grid grid-cols-4 gap-4">
        <div className="space-y-2">
          <label htmlFor="max-tokens" className={labelClass}>
            Max tokens
            <HelpBubble>Maximum number of tokens to generate before stopping.</HelpBubble>
            {isFieldModified("max_tokens") && <ResetBtn onClick={() => resetField("max_tokens")} />}
          </label>
          <input
            id="max-tokens"
            type="number"
            min={1}
            required
            className={inputClass}
            value={localMaxTokens}
            onChange={(e) => setLocalMaxTokens(e.target.value)}
            onBlur={commitMaxTokens}
          />
          <span className="field-error">Min 1</span>
        </div>
        <div className="space-y-2 col-span-3">
          <label htmlFor="stop-sequences" className={labelClass}>
            Stop sequences
            <HelpBubble>Comma separated strings that halt generation when produced.</HelpBubble>
            {isFieldModified("stop_sequences") && (
              <ResetBtn onClick={() => resetField("stop_sequences")} />
            )}
          </label>
          <input
            id="stop-sequences"
            className={inputClass}
            value={localStopSeqs}
            placeholder="comma separated"
            onChange={(e) => setLocalStopSeqs(e.target.value)}
            onBlur={commitStopSeqs}
          />
        </div>
      </div>

      {/* Row 2: THINKING + BUDGET */}
      <div className="grid grid-cols-4 gap-4">
        <div className="space-y-2 col-span-3">
          <span className={labelClass}>
            Thinking
            {thinkingHelp}
            {thinkingModified && <ResetBtn onClick={resetThinking} />}
          </span>
          <SegmentedTrack<ThinkingMode>
            ariaLabel="Thinking mode"
            value={thinkingMode}
            onChange={changeThinkingMode}
            options={[
              { label: "off", value: "off" },
              { label: "adaptive", value: "adaptive" },
              { label: "enabled", value: "enabled" },
            ]}
          />
        </div>
        <div className={`space-y-2 ${budgetEnabled ? "" : "opacity-40 pointer-events-none"}`}>
          <label htmlFor="budget" className={labelClass}>
            Budget
            <HelpBubble>
              Maximum thinking tokens the model may spend before writing its response. Minimum 1024.
              Only applies when THINKING is ENABLED.
            </HelpBubble>
          </label>
          <input
            id="budget"
            type="number"
            min={MIN_BUDGET}
            className={inputClass}
            value={localBudget}
            disabled={!budgetEnabled}
            onChange={(e) => setLocalBudget(e.target.value)}
            onBlur={commitBudget}
          />
          <span className="field-error">Min {MIN_BUDGET}</span>
        </div>
      </div>

      {/* Row 3: DISPLAY + EFFORT */}
      <div className="grid grid-cols-2 gap-4">
        <div className={`space-y-2 ${thinkingActive ? "" : "opacity-40 pointer-events-none"}`}>
          <span className={labelClass}>
            Display
            <HelpBubble>
              Controls how thinking content is returned. SUMMARIZED shows a compact summary; OMITTED
              hides thinking entirely from the response.
            </HelpBubble>
            {displayModified && <ResetBtn onClick={resetDisplay} />}
          </span>
          <SegmentedTrack<DisplayMode>
            ariaLabel="Thinking display"
            value={display}
            onChange={changeDisplay}
            disabled={!thinkingActive}
            options={[
              { label: "summarized", value: "summarized" },
              { label: "omitted", value: "omitted" },
            ]}
          />
        </div>
        <div className="space-y-2">
          <span className={labelClass}>
            Effort
            <HelpBubble>
              Provider-level reasoning effort hint. — leaves the key unset. Higher levels ask the
              model for more careful reasoning; providers that don't support effort ignore the hint.
            </HelpBubble>
            {effortModified && <ResetBtn onClick={resetEffort} />}
          </span>
          <SegmentedTrack<EffortLevel | "none">
            ariaLabel="Output effort"
            value={effort ?? "none"}
            onChange={changeEffort}
            options={[
              { label: "—", value: "none" },
              { label: "low", value: "low" },
              { label: "med", value: "medium" },
              { label: "high", value: "high" },
              { label: "max", value: "max" },
            ]}
          />
        </div>
      </div>

      {/* Row 4: TEMPERATURE + TOP K + TOP P */}
      <div className="grid grid-cols-3 gap-4">
        <div className={`space-y-2 ${thinkingActive ? "opacity-40 pointer-events-none" : ""}`}>
          <label htmlFor="temperature" className={labelClass}>
            Temperature
            <HelpBubble>
              <p>Adjusts how the model treats the probabilities of its next token options.</p>
              <p className="mt-1.5 text-txt-3">Range: 0.0 to 1.0</p>
              <ul className="mt-1.5 space-y-1 text-txt-3">
                <li>
                  <span className="text-txt-2">T=0</span> Greedy. Always picks the most likely
                  token. Deterministic, ideal for factual tasks or code.
                </li>
                <li>
                  <span className="text-txt-2">0.1 to 0.7</span> Focused and coherent. Good for
                  structured output.
                </li>
                <li>
                  <span className="text-txt-2">T=1</span> Maximum randomness. Uses raw calculated
                  probabilities.
                </li>
              </ul>
            </HelpBubble>
            {isFieldModified("temperature") && (
              <ResetBtn onClick={() => resetField("temperature")} />
            )}
          </label>
          <input
            id="temperature"
            type="number"
            step="any"
            min={0}
            max={1}
            className={inputClass}
            value={localTemp}
            disabled={thinkingActive}
            onChange={(e) => setLocalTemp(e.target.value)}
            onBlur={() => commitFloatField("temperature", localTemp, setLocalTemp)}
          />
          <span className="field-error">0 to 1</span>
        </div>
        <div className={`space-y-2 ${thinkingActive ? "opacity-40 pointer-events-none" : ""}`}>
          <label htmlFor="top-k" className={labelClass}>
            Top K
            <HelpBubble>
              <p>Restricts sampling to the K most likely next tokens.</p>
              <ul className="mt-1.5 space-y-1 text-txt-3">
                <li>
                  <span className="text-txt-2">1 to 10</span> High accuracy, coherent, less
                  creative, repetitive.
                </li>
                <li>
                  <span className="text-txt-2">10 to 50</span> Balanced. Good for general chat and
                  writing.
                </li>
                <li>
                  <span className="text-txt-2">50 to 100+</span> Higher creativity, more varied,
                  higher risk of nonsense.
                </li>
              </ul>
              <p className="mt-1.5 text-txt-3">Common default: 40</p>
            </HelpBubble>
            {isFieldModified("top_k") && <ResetBtn onClick={() => resetField("top_k")} />}
          </label>
          <input
            id="top-k"
            type="number"
            min={1}
            className={inputClass}
            value={localTopK}
            disabled={thinkingActive}
            onChange={(e) => setLocalTopK(e.target.value)}
            onBlur={commitTopK}
          />
          <span className="field-error">Min 1</span>
        </div>
        <div className={`space-y-2 ${thinkingActive ? "opacity-40 pointer-events-none" : ""}`}>
          <label htmlFor="top-p" className={labelClass}>
            Top P
            <HelpBubble>
              <p>
                Restricts sampling to the smallest set of top tokens whose cumulative probability
                exceeds P.
              </p>
              <ul className="mt-1.5 space-y-1 text-txt-3">
                <li>
                  <span className="text-txt-2">0.1 to 0.5</span> Highly deterministic, conservative,
                  focused.
                </li>
                <li>
                  <span className="text-txt-2">0.5 to 0.9</span> Good balance of diversity and
                  coherence.
                </li>
                <li>
                  <span className="text-txt-2">0.9 to 1.0</span> High creativity and variety. 1.0
                  considers all tokens.
                </li>
              </ul>
              <p className="mt-1.5 text-txt-3">Common default: 0.9 or 0.95</p>
            </HelpBubble>
            {isFieldModified("top_p") && <ResetBtn onClick={() => resetField("top_p")} />}
          </label>
          <input
            id="top-p"
            type="number"
            step="any"
            min={0}
            max={1}
            className={inputClass}
            value={localTopP}
            disabled={thinkingActive}
            onChange={(e) => setLocalTopP(e.target.value)}
            onBlur={() => commitFloatField("top_p", localTopP, setLocalTopP)}
          />
          <span className="field-error">0 to 1</span>
        </div>
      </div>
    </section>
  );
}
