import { useRef } from "react";
import type { SamplingParams } from "../../types";
import { HelpBubble } from "../HelpBubble";

interface SamplingSectionProps {
  sampling: SamplingParams;
  onChange: (sampling: SamplingParams) => void;
  providerExtras: Record<string, unknown>;
  onProviderExtrasChange: (extras: Record<string, unknown>) => void;
}

const inputClass =
  "w-full bg-canvas border border-edge px-3 py-2 text-[13px] text-txt focus:border-accent/50 focus:outline-none transition-colors metric-num";

const labelClass = "label flex items-center";

function getThinking(extras: Record<string, unknown>): {
  enabled: boolean;
  budgetTokens: number;
} {
  const thinking = extras.thinking as Record<string, unknown> | undefined;
  if (!thinking || typeof thinking !== "object") return { enabled: false, budgetTokens: 10000 };
  return {
    enabled: thinking.type === "enabled",
    budgetTokens: typeof thinking.budget_tokens === "number" ? thinking.budget_tokens : 10000,
  };
}

export function SamplingSection({
  sampling,
  onChange,
  providerExtras,
  onProviderExtrasChange,
}: SamplingSectionProps) {
  const { enabled: thinkingEnabled, budgetTokens } = getThinking(providerExtras);
  const budgetRef = useRef(budgetTokens);
  if (thinkingEnabled) budgetRef.current = budgetTokens;

  const handleSampling = (field: keyof SamplingParams, raw: string) => {
    if (field === "stop_sequences") {
      const seqs = raw
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      onChange({ ...sampling, stop_sequences: seqs });
      return;
    }

    if (field === "max_tokens") {
      const n = Number.parseInt(raw, 10);
      if (Number.isNaN(n)) return;
      onChange({ ...sampling, max_tokens: n });
      return;
    }

    const val = raw.trim() === "" ? null : Number(raw);
    if (val !== null && Number.isNaN(val)) return;

    if (field === "top_k") {
      onChange({ ...sampling, top_k: val === null ? null : Math.round(val) });
    } else {
      onChange({ ...sampling, [field]: val });
    }
  };

  const handleThinkingToggle = (next: boolean) => {
    const thinking = next
      ? { type: "enabled", budget_tokens: budgetRef.current }
      : { type: "disabled" };
    onProviderExtrasChange({ ...providerExtras, thinking });
    if (next) {
      onChange({ ...sampling, temperature: null, top_k: null, top_p: null });
    } else {
      onChange({ ...sampling, temperature: 1 });
    }
  };

  return (
    <section className="space-y-4">
      <div className="section-rule">
        <span className="label">Sampling</span>
      </div>
      <div className="grid grid-cols-4 gap-4">
        {/* Row 1 */}
        <div className="space-y-2">
          <label htmlFor="max-tokens" className={labelClass}>
            Max tokens
            <HelpBubble>Maximum number of tokens to generate before stopping.</HelpBubble>
          </label>
          <input
            id="max-tokens"
            type="number"
            min={1}
            required
            className={inputClass}
            value={sampling.max_tokens}
            onChange={(e) => handleSampling("max_tokens", e.target.value)}
          />
          <span className="field-error">Min 1</span>
        </div>
        <div className="space-y-2 col-span-3">
          <label htmlFor="stop-sequences" className={labelClass}>
            Stop sequences
            <HelpBubble>Comma separated strings that halt generation when produced.</HelpBubble>
          </label>
          <input
            id="stop-sequences"
            className={inputClass}
            value={sampling.stop_sequences.join(", ")}
            placeholder="comma separated"
            onChange={(e) => handleSampling("stop_sequences", e.target.value)}
          />
        </div>

        {/* Row 2 */}
        <div className="space-y-2">
          <span className={labelClass}>
            Thinking
            <HelpBubble>
              <p>
                Enable thinking to allow the model to perform internal reasoning and step by step
                logic before responding.
              </p>
              <p className="mt-2 text-txt-2">Turn it ON when:</p>
              <ul className="mt-1 space-y-0.5 text-txt-3">
                <li>
                  <span className="text-txt-2">Complex Coding</span> Debugging deep logic,
                  refactoring large files, or architectural planning.
                </li>
                <li>
                  <span className="text-txt-2">Multi Step Math/Science</span> Advanced equations or
                  problems requiring a chain of thought.
                </li>
                <li>
                  <span className="text-txt-2">Strategic Planning</span> Nuanced breakdown of
                  business cases, legal documents, or technical specs.
                </li>
                <li>
                  <span className="text-txt-2">Ambiguous Prompts</span> Requests with many moving
                  parts or constraints to organize.
                </li>
              </ul>
              <p className="mt-2 text-txt-2">Keep it OFF when:</p>
              <ul className="mt-1 space-y-0.5 text-txt-3">
                <li>
                  <span className="text-txt-2">Speed is Priority</span> Instant answers for simple
                  lookups or basic facts.
                </li>
                <li>
                  <span className="text-txt-2">Creative Drafting</span> Brainstorming, poems, or
                  casual emails where overthinking is unnecessary.
                </li>
                <li>
                  <span className="text-txt-2">Basic Tasks</span> Routine translations, summaries,
                  or simple formatting.
                </li>
              </ul>
              <p className="mt-2 text-txt-3">When enabled, temperature/top_k/top_p are locked.</p>
            </HelpBubble>
          </span>
          <button
            type="button"
            onClick={() => handleThinkingToggle(!thinkingEnabled)}
            className={`w-full h-[38px] border px-3 text-[13px] metric-num text-left cursor-pointer transition-colors ${
              thinkingEnabled
                ? "bg-lavender/10 border-lavender/40 text-lavender"
                : "bg-canvas border-edge text-txt-3 hover:border-txt-3"
            }`}
          >
            {thinkingEnabled ? `THINKING  ${budgetTokens.toLocaleString()}` : "THINKING  off"}
          </button>
        </div>
        <div className={`space-y-2 ${thinkingEnabled ? "opacity-40 pointer-events-none" : ""}`}>
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
          </label>
          <input
            id="temperature"
            type="number"
            step="any"
            min={0}
            max={1}
            className={inputClass}
            value={sampling.temperature ?? ""}
            disabled={thinkingEnabled}
            onChange={(e) => handleSampling("temperature", e.target.value)}
          />
          <span className="field-error">0 to 1</span>
        </div>
        <div className={`space-y-2 ${thinkingEnabled ? "opacity-40 pointer-events-none" : ""}`}>
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
          </label>
          <input
            id="top-k"
            type="number"
            min={1}
            className={inputClass}
            value={sampling.top_k ?? ""}
            disabled={thinkingEnabled}
            onChange={(e) => handleSampling("top_k", e.target.value)}
          />
          <span className="field-error">Min 1</span>
        </div>
        <div className={`space-y-2 ${thinkingEnabled ? "opacity-40 pointer-events-none" : ""}`}>
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
          </label>
          <input
            id="top-p"
            type="number"
            step="any"
            min={0}
            max={1}
            className={inputClass}
            value={sampling.top_p ?? ""}
            disabled={thinkingEnabled}
            onChange={(e) => handleSampling("top_p", e.target.value)}
          />
          <span className="field-error">0 to 1</span>
        </div>
      </div>
    </section>
  );
}
