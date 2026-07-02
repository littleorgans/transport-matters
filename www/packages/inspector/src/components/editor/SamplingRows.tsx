import type { SamplingParams } from "@tm/core/types/ir";
import { HelpBubble } from "../HelpBubble";
import {
  type DisplayMode,
  type EffortLevel,
  MIN_BUDGET,
  type ThinkingMode,
} from "./samplingShared";

const inputClass =
  "w-full bg-canvas border border-edge px-3 py-2 text-[13px] text-txt focus:border-accent/50 focus:outline-none transition-colors metric-num";

const labelClass = "label flex items-center";

type IsFieldModified = (field: keyof SamplingParams) => boolean;
type ResetField = (field: keyof SamplingParams) => void;

function ResetButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      className="label ml-2 cursor-pointer text-txt-3 transition-colors hover:text-amber"
      onClick={onClick}
    >
      reset
    </button>
  );
}

interface SegmentOption<T extends string> {
  label: string;
  value: T;
}

interface SegmentedTrackProps<T extends string> {
  value: T;
  options: readonly SegmentOption<T>[];
  onChange: (value: T) => void;
  disabled?: boolean;
  readOnly?: boolean;
  ariaLabel: string;
}

function SegmentedTrack<T extends string>({
  value,
  options,
  onChange,
  disabled = false,
  readOnly = false,
  ariaLabel,
}: SegmentedTrackProps<T>) {
  const inert = disabled || readOnly;

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={`flex border border-edge bg-canvas divide-x divide-edge ${
        disabled ? "opacity-40 pointer-events-none" : readOnly ? "pointer-events-none" : ""
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
            disabled={inert}
            onClick={() => onChange(opt.value)}
            className={`flex-1 px-3 py-1.5 uppercase text-[11px] tracking-[0.2em] cursor-pointer transition-colors ${
              selected
                ? "bg-sage/15 text-txt"
                : readOnly
                  ? "text-txt-3"
                  : "text-txt-3 hover:text-txt-2"
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

interface SamplingBasicsRowProps {
  readOnly: boolean;
  localMaxTokens: string;
  localStopSeqs: string;
  setLocalMaxTokens: (value: string) => void;
  setLocalStopSeqs: (value: string) => void;
  commitMaxTokens: () => void;
  commitStopSeqs: () => void;
  isFieldModified: IsFieldModified;
  resetField: ResetField;
}

export function SamplingBasicsRow({
  readOnly,
  localMaxTokens,
  localStopSeqs,
  setLocalMaxTokens,
  setLocalStopSeqs,
  commitMaxTokens,
  commitStopSeqs,
  isFieldModified,
  resetField,
}: SamplingBasicsRowProps) {
  return (
    <div className="grid grid-cols-4 gap-4">
      <div className="space-y-2">
        <label htmlFor="max-tokens" className={labelClass}>
          Max tokens
          <HelpBubble>Maximum number of tokens to generate before stopping.</HelpBubble>
          {!readOnly && isFieldModified("max_tokens") && (
            <ResetButton onClick={() => resetField("max_tokens")} />
          )}
        </label>
        <input
          id="max-tokens"
          type="number"
          min={1}
          required
          className={inputClass}
          value={localMaxTokens}
          readOnly={readOnly}
          onChange={(e) => setLocalMaxTokens(e.target.value)}
          onBlur={commitMaxTokens}
        />
        <span className="field-error">Min 1</span>
      </div>
      <div className="space-y-2 col-span-3">
        <label htmlFor="stop-sequences" className={labelClass}>
          Stop sequences
          <HelpBubble>Comma separated strings that halt generation when produced.</HelpBubble>
          {!readOnly && isFieldModified("stop_sequences") && (
            <ResetButton onClick={() => resetField("stop_sequences")} />
          )}
        </label>
        <input
          id="stop-sequences"
          className={inputClass}
          value={localStopSeqs}
          placeholder="comma separated"
          readOnly={readOnly}
          onChange={(e) => setLocalStopSeqs(e.target.value)}
          onBlur={commitStopSeqs}
        />
      </div>
    </div>
  );
}

interface ThinkingRowProps {
  readOnly: boolean;
  thinkingMode: ThinkingMode;
  thinkingModified: boolean;
  budgetEnabled: boolean;
  localBudget: string;
  setLocalBudget: (value: string) => void;
  commitBudget: () => void;
  resetThinking: () => void;
  changeThinkingMode: (mode: ThinkingMode) => void;
}

export function ThinkingRow({
  readOnly,
  thinkingMode,
  thinkingModified,
  budgetEnabled,
  localBudget,
  setLocalBudget,
  commitBudget,
  resetThinking,
  changeThinkingMode,
}: ThinkingRowProps) {
  return (
    <div className="grid grid-cols-4 gap-4">
      <div className="space-y-2 col-span-3">
        <span className={labelClass}>
          Thinking
          <HelpBubble>
            <p>
              <span className="text-txt-2">OFF</span> No internal reasoning. Fast, direct responses.
            </p>
            <p className="mt-1.5">
              <span className="text-txt-2">ADAPTIVE</span> The model decides when to think based on
              the prompt.
            </p>
            <p className="mt-1.5">
              <span className="text-txt-2">ENABLED</span> Always think. Budget controls the maximum
              thinking tokens.
            </p>
            <p className="mt-2 text-txt-3">
              When thinking is on, temperature/top_k/top_p are locked to defaults.
            </p>
          </HelpBubble>
          {!readOnly && thinkingModified && <ResetButton onClick={resetThinking} />}
        </span>
        <SegmentedTrack<ThinkingMode>
          ariaLabel="Thinking mode"
          value={thinkingMode}
          onChange={changeThinkingMode}
          readOnly={readOnly}
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
          readOnly={readOnly}
          disabled={!budgetEnabled}
          onChange={(e) => setLocalBudget(e.target.value)}
          onBlur={commitBudget}
        />
        <span className="field-error">Min {MIN_BUDGET}</span>
      </div>
    </div>
  );
}

interface ProviderExtrasRowProps {
  readOnly: boolean;
  thinkingActive: boolean;
  display: DisplayMode;
  effort: EffortLevel | null;
  displayModified: boolean;
  effortModified: boolean;
  resetDisplay: () => void;
  resetEffort: () => void;
  changeDisplay: (display: DisplayMode) => void;
  changeEffort: (effort: EffortLevel | "none") => void;
}

export function ProviderExtrasRow({
  readOnly,
  thinkingActive,
  display,
  effort,
  displayModified,
  effortModified,
  resetDisplay,
  resetEffort,
  changeDisplay,
  changeEffort,
}: ProviderExtrasRowProps) {
  return (
    <div className="grid grid-cols-2 gap-4">
      <div className={`space-y-2 ${thinkingActive ? "" : "opacity-40 pointer-events-none"}`}>
        <span className={labelClass}>
          Display
          <HelpBubble>
            Controls how thinking content is returned. SUMMARIZED shows a compact summary; OMITTED
            hides thinking entirely from the response.
          </HelpBubble>
          {!readOnly && displayModified && <ResetButton onClick={resetDisplay} />}
        </span>
        <SegmentedTrack<DisplayMode>
          ariaLabel="Thinking display"
          value={display}
          onChange={changeDisplay}
          disabled={!thinkingActive}
          readOnly={readOnly}
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
          {!readOnly && effortModified && <ResetButton onClick={resetEffort} />}
        </span>
        <SegmentedTrack<EffortLevel | "none">
          ariaLabel="Output effort"
          value={effort ?? "none"}
          onChange={changeEffort}
          readOnly={readOnly}
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
  );
}

interface SamplingKnobsRowProps {
  readOnly: boolean;
  thinkingActive: boolean;
  localTemp: string;
  localTopK: string;
  localTopP: string;
  setLocalTemp: (value: string) => void;
  setLocalTopK: (value: string) => void;
  setLocalTopP: (value: string) => void;
  commitFloatField: (
    field: "temperature" | "top_p",
    raw: string,
    resetLocal: (value: string) => void,
  ) => void;
  commitTopK: () => void;
  isFieldModified: IsFieldModified;
  resetField: ResetField;
}

export function SamplingKnobsRow({
  readOnly,
  thinkingActive,
  localTemp,
  localTopK,
  localTopP,
  setLocalTemp,
  setLocalTopK,
  setLocalTopP,
  commitFloatField,
  commitTopK,
  isFieldModified,
  resetField,
}: SamplingKnobsRowProps) {
  return (
    <div className="grid grid-cols-3 gap-4">
      <div className={`space-y-2 ${thinkingActive ? "opacity-40 pointer-events-none" : ""}`}>
        <label htmlFor="temperature" className={labelClass}>
          Temperature
          <HelpBubble>
            <p>Adjusts how the model treats the probabilities of its next token options.</p>
            <p className="mt-1.5 text-txt-3">Range: 0.0 to 1.0</p>
            <ul className="mt-1.5 space-y-1 text-txt-3">
              <li>
                <span className="text-txt-2">T=0</span> Greedy. Always picks the most likely token.
                Deterministic, ideal for factual tasks or code.
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
          {!readOnly && isFieldModified("temperature") && (
            <ResetButton onClick={() => resetField("temperature")} />
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
          readOnly={readOnly || thinkingActive}
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
                <span className="text-txt-2">1 to 10</span> High accuracy, coherent, less creative,
                repetitive.
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
          {!readOnly && isFieldModified("top_k") && (
            <ResetButton onClick={() => resetField("top_k")} />
          )}
        </label>
        <input
          id="top-k"
          type="number"
          min={1}
          className={inputClass}
          value={localTopK}
          readOnly={readOnly || thinkingActive}
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
          {!readOnly && isFieldModified("top_p") && (
            <ResetButton onClick={() => resetField("top_p")} />
          )}
        </label>
        <input
          id="top-p"
          type="number"
          step="any"
          min={0}
          max={1}
          className={inputClass}
          value={localTopP}
          readOnly={readOnly || thinkingActive}
          disabled={thinkingActive}
          onChange={(e) => setLocalTopP(e.target.value)}
          onBlur={() => commitFloatField("top_p", localTopP, setLocalTopP)}
        />
        <span className="field-error">0 to 1</span>
      </div>
    </div>
  );
}
