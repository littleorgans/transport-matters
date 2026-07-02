import { useRef } from "react";
import { useSyncedLocalValue } from "../../hooks/useSyncedLocalValue";
import { hasOverride } from "../../lib/overrides";
import type { Override, SamplingParams } from "../../types";
import {
  DISPLAY_TARGET,
  type DisplayMode,
  EFFORT_TARGET,
  type EffortLevel,
  getBudget,
  getDisplay,
  getEffort,
  getThinkingMode,
  MIN_BUDGET,
  readThinkingDict,
  SAMPLING_TARGETS,
  THINKING_TARGET,
  type ThinkingMode,
} from "./samplingShared";

interface UseThinkingOverridesArgs {
  originalSampling: SamplingParams;
  providerExtras: Record<string, unknown>;
  originalProviderExtras: Record<string, unknown>;
  overrides: Override[];
  onOverride: (batch: Override[]) => void;
}

export function useThinkingOverrides({
  originalSampling,
  providerExtras,
  originalProviderExtras,
  overrides,
  onOverride,
}: UseThinkingOverridesArgs) {
  const thinkingMode = getThinkingMode(providerExtras);
  const budget = getBudget(providerExtras);
  const display = getDisplay(providerExtras);
  const effort = getEffort(providerExtras);

  const thinkingActive = thinkingMode !== "off";
  const budgetEnabled = thinkingMode === "enabled";

  const budgetRef = useRef(budget);
  if (budgetEnabled) budgetRef.current = budget;

  const [localBudget, setLocalBudget] = useSyncedLocalValue(String(budget));

  const thinkingModified = hasOverride(overrides, "provider_extras_set", THINKING_TARGET);
  const displayModified = hasOverride(overrides, "provider_extras_set", DISPLAY_TARGET);
  const effortModified = hasOverride(overrides, "provider_extras_set", EFFORT_TARGET);

  const commitBudget = () => {
    const n = Number.parseInt(localBudget, 10);
    if (Number.isNaN(n) || n < MIN_BUDGET) {
      setLocalBudget(String(budget));
      return;
    }
    const originalMode = getThinkingMode(originalProviderExtras);
    const originalBudget = getBudget(originalProviderExtras);
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

    if (next === "off") {
      const originalHadThinking = readThinkingDict(originalProviderExtras) !== null;
      batch.push({
        kind: "provider_extras_set",
        target: THINKING_TARGET,
        value: originalHadThinking ? "null" : null,
      });
      batch.push({ kind: "provider_extras_set", target: DISPLAY_TARGET, value: null });
    } else if (next === "adaptive") {
      batch.push({
        kind: "provider_extras_set",
        target: THINKING_TARGET,
        value: JSON.stringify({ type: "adaptive" }),
      });
    } else {
      batch.push({
        kind: "provider_extras_set",
        target: THINKING_TARGET,
        value: JSON.stringify({ type: "enabled", budget_tokens: budgetRef.current }),
      });
    }

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
    const nextEffort = next === "none" ? null : next;
    if (nextEffort === effort) return;
    const originalEffort = getEffort(originalProviderExtras);
    if (nextEffort === originalEffort) {
      onOverride([{ kind: "provider_extras_set", target: EFFORT_TARGET, value: null }]);
      return;
    }
    const jsonValue = nextEffort === null ? "null" : JSON.stringify(nextEffort);
    onOverride([{ kind: "provider_extras_set", target: EFFORT_TARGET, value: jsonValue }]);
  };

  return {
    thinkingMode,
    budget,
    display,
    effort,
    thinkingActive,
    budgetEnabled,
    localBudget,
    setLocalBudget,
    thinkingModified,
    displayModified,
    effortModified,
    commitBudget,
    resetThinking,
    resetDisplay,
    resetEffort,
    changeThinkingMode,
    changeDisplay,
    changeEffort,
  };
}
