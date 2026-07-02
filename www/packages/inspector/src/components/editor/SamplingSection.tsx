import type { SamplingParams } from "@tm/core/types/ir";
import type { Override } from "@tm/core/types/overrides";
import { overrideCountLabel } from "./overrideUtils";
import {
  ProviderExtrasRow,
  SamplingBasicsRow,
  SamplingKnobsRow,
  ThinkingRow,
} from "./SamplingRows";
import { useSamplingOverrides } from "./useSamplingOverrides";
import { useThinkingOverrides } from "./useThinkingOverrides";

/**
 * SAMPLING section. All edits flow through the override pipeline as
 * ``sampling_set`` and ``provider_extras_set`` so the audit ledger tracks
 * knob edits alongside content edits and the "Save as overlay" action
 * captures them durably.
 *
 * Values ride on ``Override.value`` as JSON-encoded strings so a scalar
 * ``str | bool | int | null`` union can carry floats, lists, and objects
 * without widening the Override schema; the backend parses on apply.
 * Dotted-path targets (``provider_extras:thinking.display``,
 * ``provider_extras:output_config.effort``) let DISPLAY and EFFORT land
 * at specific nested keys without clobbering siblings.
 *
 * Fields commit on blur rather than per-keystroke so each logical edit
 * emits one override (not N) and the network side stays quiet while the
 * user is typing.
 */

interface SamplingSectionProps {
  sampling: SamplingParams;
  /**
   * Pristine sampling from the paused flow's ``original_ir``. Used to
   * decide "commit clears the override" when the user edits back to the
   * source value, so the ledger doesn't carry redundant no-op entries.
   */
  originalSampling: SamplingParams;
  providerExtras: Record<string, unknown>;
  originalProviderExtras: Record<string, unknown>;
  overrides: Override[];
  onOverride: (batch: Override[]) => void;
  readOnly?: boolean;
}

export function SamplingSection({
  sampling,
  originalSampling,
  providerExtras,
  originalProviderExtras,
  overrides,
  onOverride,
  readOnly = false,
}: SamplingSectionProps) {
  const samplingOverrides = useSamplingOverrides({
    sampling,
    originalSampling,
    overrides,
    onOverride,
  });
  const thinkingOverrides = useThinkingOverrides({
    originalSampling,
    providerExtras,
    originalProviderExtras,
    overrides,
    onOverride,
  });

  const samplingOverrideCount = overrides.filter(
    (o) => o.kind === "sampling_set" || o.kind === "provider_extras_set",
  ).length;

  return (
    <section className="space-y-4">
      <div className="section-rule">
        <span className="label">Sampling</span>
        {samplingOverrideCount > 0 && (
          <span className="chip text-amber ml-2">
            {samplingOverrideCount} {overrideCountLabel(samplingOverrideCount, readOnly)}
          </span>
        )}
      </div>

      <SamplingBasicsRow
        readOnly={readOnly}
        localMaxTokens={samplingOverrides.localMaxTokens}
        localStopSeqs={samplingOverrides.localStopSeqs}
        setLocalMaxTokens={samplingOverrides.setLocalMaxTokens}
        setLocalStopSeqs={samplingOverrides.setLocalStopSeqs}
        commitMaxTokens={samplingOverrides.commitMaxTokens}
        commitStopSeqs={samplingOverrides.commitStopSeqs}
        isFieldModified={samplingOverrides.isFieldModified}
        resetField={samplingOverrides.resetField}
      />

      <ThinkingRow
        readOnly={readOnly}
        thinkingMode={thinkingOverrides.thinkingMode}
        thinkingModified={thinkingOverrides.thinkingModified}
        budgetEnabled={thinkingOverrides.budgetEnabled}
        localBudget={thinkingOverrides.localBudget}
        setLocalBudget={thinkingOverrides.setLocalBudget}
        commitBudget={thinkingOverrides.commitBudget}
        resetThinking={thinkingOverrides.resetThinking}
        changeThinkingMode={thinkingOverrides.changeThinkingMode}
      />

      <ProviderExtrasRow
        readOnly={readOnly}
        thinkingActive={thinkingOverrides.thinkingActive}
        display={thinkingOverrides.display}
        effort={thinkingOverrides.effort}
        displayModified={thinkingOverrides.displayModified}
        effortModified={thinkingOverrides.effortModified}
        resetDisplay={thinkingOverrides.resetDisplay}
        resetEffort={thinkingOverrides.resetEffort}
        changeDisplay={thinkingOverrides.changeDisplay}
        changeEffort={thinkingOverrides.changeEffort}
      />

      <SamplingKnobsRow
        readOnly={readOnly}
        thinkingActive={thinkingOverrides.thinkingActive}
        localTemp={samplingOverrides.localTemp}
        localTopK={samplingOverrides.localTopK}
        localTopP={samplingOverrides.localTopP}
        setLocalTemp={samplingOverrides.setLocalTemp}
        setLocalTopK={samplingOverrides.setLocalTopK}
        setLocalTopP={samplingOverrides.setLocalTopP}
        commitFloatField={samplingOverrides.commitFloatField}
        commitTopK={samplingOverrides.commitTopK}
        isFieldModified={samplingOverrides.isFieldModified}
        resetField={samplingOverrides.resetField}
      />
    </section>
  );
}
