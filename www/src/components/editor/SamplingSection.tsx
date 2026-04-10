import type { SamplingParams } from "../../types";

interface SamplingSectionProps {
  sampling: SamplingParams;
  onChange: (sampling: SamplingParams) => void;
}

const inputClass =
  "w-full bg-canvas border border-edge px-3 py-2 text-[11px] text-txt focus:border-sky/50 focus:outline-none transition-colors metric-num";

const labelClass = "label block";

export function SamplingSection({ sampling, onChange }: SamplingSectionProps) {
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

  return (
    <section className="space-y-4">
      <div className="section-rule">
        <span className="label">Sampling</span>
      </div>
      <div className="grid grid-cols-3 gap-4">
        <div className="space-y-2">
          <label htmlFor="max-tokens" className={labelClass}>
            Max tokens
          </label>
          <input
            id="max-tokens"
            type="number"
            className={inputClass}
            value={sampling.max_tokens}
            onChange={(e) => handleSampling("max_tokens", e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <label htmlFor="temperature" className={labelClass}>
            Temperature
          </label>
          <input
            id="temperature"
            type="number"
            step="0.1"
            className={inputClass}
            value={sampling.temperature ?? ""}
            onChange={(e) => handleSampling("temperature", e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <label htmlFor="top-p" className={labelClass}>
            Top P
          </label>
          <input
            id="top-p"
            type="number"
            step="0.05"
            className={inputClass}
            value={sampling.top_p ?? ""}
            onChange={(e) => handleSampling("top_p", e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <label htmlFor="top-k" className={labelClass}>
            Top K
          </label>
          <input
            id="top-k"
            type="number"
            className={inputClass}
            value={sampling.top_k ?? ""}
            onChange={(e) => handleSampling("top_k", e.target.value)}
          />
        </div>
        <div className="space-y-2 col-span-2">
          <label htmlFor="stop-sequences" className={labelClass}>
            Stop sequences
          </label>
          <input
            id="stop-sequences"
            className={inputClass}
            value={sampling.stop_sequences.join(", ")}
            placeholder="comma separated"
            onChange={(e) => handleSampling("stop_sequences", e.target.value)}
          />
        </div>
      </div>
    </section>
  );
}
