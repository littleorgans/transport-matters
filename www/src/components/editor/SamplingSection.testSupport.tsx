import { fireEvent, render, screen, within } from "@testing-library/react";
import { vi } from "vitest";
import type { Override, SamplingParams } from "../../types";
import { SamplingSection } from "./SamplingSection";

// Pristine reference the editor passes through as ``originalSampling``.
// Tests that need to assert "edit back to original clears the override"
// diff their commit against this shape.
const ORIGINAL_SAMPLING: SamplingParams = {
  max_tokens: 1024,
  temperature: 0.7,
  top_p: null,
  top_k: null,
  stop_sequences: [],
};

export function renderSection(
  opts: {
    sampling?: Partial<SamplingParams>;
    originalSampling?: Partial<SamplingParams>;
    providerExtras?: Record<string, unknown>;
    originalProviderExtras?: Record<string, unknown>;
    overrides?: Override[];
  } = {},
) {
  const sampling: SamplingParams = { ...ORIGINAL_SAMPLING, ...(opts.sampling ?? {}) };
  const originalSampling: SamplingParams = {
    ...ORIGINAL_SAMPLING,
    ...(opts.originalSampling ?? {}),
  };
  const onOverride = vi.fn();
  render(
    <SamplingSection
      sampling={sampling}
      originalSampling={originalSampling}
      providerExtras={opts.providerExtras ?? {}}
      originalProviderExtras={opts.originalProviderExtras ?? {}}
      overrides={opts.overrides ?? []}
      onOverride={onOverride}
    />,
  );
  return { onOverride };
}

// Each segmented-track surface renders as a tablist with tab buttons. Scoping
// clicks through the tablist avoids collisions with reset buttons.
export function clickThinking(mode: "off" | "adaptive" | "enabled") {
  const group = screen.getByRole("tablist", { name: "Thinking mode" });
  fireEvent.click(within(group).getByRole("tab", { name: mode }));
}

export function clickDisplay(mode: "summarized" | "omitted") {
  const group = screen.getByRole("tablist", { name: "Thinking display" });
  fireEvent.click(within(group).getByRole("tab", { name: mode }));
}

export function clickEffort(label: "—" | "low" | "med" | "high" | "max") {
  const group = screen.getByRole("tablist", { name: "Output effort" });
  fireEvent.click(within(group).getByRole("tab", { name: label }));
}
