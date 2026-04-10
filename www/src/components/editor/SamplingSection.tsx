import type { InternalRequest, SamplingParams } from "../../types";

interface SamplingSectionProps {
  sampling: SamplingParams;
  model: string;
  onChange: (updates: Partial<InternalRequest>) => void;
}

const inputClass =
  "w-full rounded-md bg-canvas border border-edge px-3 py-2 text-[11px] text-txt focus:border-sky/40 focus:outline-none transition-colors";

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

  return (
    <div className="space-y-3">
      <h3 className="text-[10px] font-medium text-txt-3 uppercase tracking-[0.12em]">Sampling</h3>
      <div className="grid grid-cols-3 gap-3">
        <div className="space-y-1">
          <label htmlFor="model" className="text-[10px] text-txt-3">
            Model
          </label>
          <input
            id="model"
            className={inputClass}
            value={model}
            onChange={(e) => handleModel(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <label htmlFor="max-tokens" className="text-[10px] text-txt-3">
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
        <div className="space-y-1">
          <label htmlFor="temperature" className="text-[10px] text-txt-3">
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
        <div className="space-y-1">
          <label htmlFor="top-p" className="text-[10px] text-txt-3">
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
        <div className="space-y-1">
          <label htmlFor="top-k" className="text-[10px] text-txt-3">
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
        <div className="space-y-1">
          <label htmlFor="stop-sequences" className="text-[10px] text-txt-3">
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
    </div>
  );
}
