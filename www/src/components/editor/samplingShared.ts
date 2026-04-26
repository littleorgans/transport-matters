import type { SamplingParams } from "../../types";

export type ThinkingMode = "off" | "adaptive" | "enabled";
export type DisplayMode = "summarized" | "omitted";
export type EffortLevel = "low" | "medium" | "high" | "max";

export const THINKING_TARGET = "provider_extras:thinking";
export const DISPLAY_TARGET = "provider_extras:thinking.display";
export const EFFORT_TARGET = "provider_extras:output_config.effort";

export const SAMPLING_TARGETS: Record<keyof SamplingParams, string> = {
  max_tokens: "sampling:max_tokens",
  temperature: "sampling:temperature",
  top_p: "sampling:top_p",
  top_k: "sampling:top_k",
  stop_sequences: "sampling:stop_sequences",
};

export const MIN_BUDGET = 1024;
export const DEFAULT_BUDGET = 10000;

export function readThinkingDict(extras: Record<string, unknown>): Record<string, unknown> | null {
  const thinking = extras.thinking;
  if (!thinking || typeof thinking !== "object") return null;
  return thinking as Record<string, unknown>;
}

export function getThinkingMode(extras: Record<string, unknown>): ThinkingMode {
  const thinking = readThinkingDict(extras);
  if (!thinking) return "off";
  if (thinking.type === "adaptive") return "adaptive";
  if (thinking.type === "enabled") return "enabled";
  return "off";
}

export function getBudget(extras: Record<string, unknown>): number {
  const thinking = readThinkingDict(extras);
  if (thinking && typeof thinking.budget_tokens === "number") return thinking.budget_tokens;
  return DEFAULT_BUDGET;
}

export function getDisplay(extras: Record<string, unknown>): DisplayMode {
  const thinking = readThinkingDict(extras);
  if (thinking && thinking.display === "omitted") return "omitted";
  return "summarized";
}

export function getEffort(extras: Record<string, unknown>): EffortLevel | null {
  const outputConfig = extras.output_config;
  if (!outputConfig || typeof outputConfig !== "object") return null;
  const effort = (outputConfig as Record<string, unknown>).effort;
  if (effort === "low" || effort === "medium" || effort === "high" || effort === "max") {
    return effort;
  }
  return null;
}

export function stopSeqsEqual(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

export function samplingValuesEqual<K extends keyof SamplingParams>(
  field: K,
  a: SamplingParams[K],
  b: SamplingParams[K],
): boolean {
  if (field === "stop_sequences") {
    return stopSeqsEqual(a as string[], b as string[]);
  }
  return a === b;
}
