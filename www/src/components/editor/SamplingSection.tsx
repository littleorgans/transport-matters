import type { InternalRequest, SamplingParams } from "../../types";

interface SamplingSectionProps {
  sampling: SamplingParams;
  model: string;
  onChange: (updates: Partial<InternalRequest>) => void;
}

export function SamplingSection({ sampling, model, onChange }: SamplingSectionProps) {
  const handleModel = (value: string) => {
    onChange({ model: value });
  };

  const handleSampling = (field: keyof SamplingParams, raw: string) => {
    let parsed: SamplingParams;

    if (field === "stop_sequences") {
      const seqs = raw
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      parsed = { ...sampling, stop_sequences: seqs };
    } else if (field === "max_tokens") {
      const n = Number.parseInt(raw, 10);
      if (Number.isNaN(n)) return;
      parsed = { ...sampling, max_tokens: n };
    } else {
      // Nullable numeric fields: temperature, top_p, top_k
      const val = raw.trim() === "" ? null : Number(raw);
      if (val !== null && Number.isNaN(val)) return;

      if (field === "top_k") {
        parsed = { ...sampling, top_k: val === null ? null : Math.round(val) };
      } else {
        parsed = { ...sampling, [field]: val };
      }
    }

    onChange({ sampling: parsed });
  };

  const labelClass = "text-xs text-zinc-500";
  const inputClass =
    "w-full rounded bg-zinc-800 px-2 py-1 text-xs text-zinc-200 border border-zinc-700 focus:border-zinc-500 focus:outline-none";

  return (
    <div className="space-y-2">
      <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Sampling</h3>
      <div className="grid grid-cols-3 gap-2">
        <div>
          <label htmlFor="model" className={labelClass}>
            Model
          </label>
          <input
            id="model"
            className={inputClass}
            value={model}
            onChange={(e) => handleModel(e.target.value)}
          />
        </div>
        <div>
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
        <div>
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
        <div>
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
        <div>
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
        <div>
          <label htmlFor="stop-sequences" className={labelClass}>
            Stop sequences
          </label>
          <input
            id="stop-sequences"
            className={inputClass}
            value={sampling.stop_sequences.join(", ")}
            placeholder="comma-separated"
            onChange={(e) => handleSampling("stop_sequences", e.target.value)}
          />
        </div>
      </div>
    </div>
  );
}
