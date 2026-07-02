import { useSyncedLocalValue } from "../../hooks/useSyncedLocalValue";
import { hasOverride } from "../../lib/overrides";
import type { Override, SamplingParams } from "../../types";
import { SAMPLING_TARGETS, samplingValuesEqual } from "./samplingShared";

interface UseSamplingOverridesArgs {
  sampling: SamplingParams;
  originalSampling: SamplingParams;
  overrides: Override[];
  onOverride: (batch: Override[]) => void;
}

function buildCommit<K extends keyof SamplingParams>(
  field: K,
  newValue: SamplingParams[K],
  originalValue: SamplingParams[K],
): Override {
  const target = SAMPLING_TARGETS[field];
  if (samplingValuesEqual(field, newValue, originalValue)) {
    return { kind: "sampling_set", target, value: null };
  }
  return { kind: "sampling_set", target, value: JSON.stringify(newValue) };
}

export function useSamplingOverrides({
  sampling,
  originalSampling,
  overrides,
  onOverride,
}: UseSamplingOverridesArgs) {
  const [localMaxTokens, setLocalMaxTokens] = useSyncedLocalValue(String(sampling.max_tokens));
  const [localTemp, setLocalTemp] = useSyncedLocalValue(
    sampling.temperature == null ? "" : String(sampling.temperature),
  );
  const [localTopP, setLocalTopP] = useSyncedLocalValue(
    sampling.top_p == null ? "" : String(sampling.top_p),
  );
  const [localTopK, setLocalTopK] = useSyncedLocalValue(
    sampling.top_k == null ? "" : String(sampling.top_k),
  );
  const stopSequenceText = sampling.stop_sequences.join(", ");
  const [localStopSeqs, setLocalStopSeqs] = useSyncedLocalValue(
    stopSequenceText,
    JSON.stringify(sampling.stop_sequences),
  );

  const isFieldModified = (field: keyof SamplingParams): boolean =>
    hasOverride(overrides, "sampling_set", SAMPLING_TARGETS[field]);

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

  const resetField = (field: keyof SamplingParams) => {
    onOverride([{ kind: "sampling_set", target: SAMPLING_TARGETS[field], value: null }]);
  };

  return {
    localMaxTokens,
    localTemp,
    localTopP,
    localTopK,
    localStopSeqs,
    setLocalMaxTokens,
    setLocalTemp,
    setLocalTopP,
    setLocalTopK,
    setLocalStopSeqs,
    isFieldModified,
    commitMaxTokens,
    commitFloatField,
    commitTopK,
    commitStopSeqs,
    resetField,
  };
}
