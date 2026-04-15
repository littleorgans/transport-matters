import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
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

function renderSection(
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

// ── Segmented-track helpers ──────────────────────────────────────────
// Each segmented-track surface (THINKING / DISPLAY / EFFORT) renders as
// role="tablist" with aria-label, containing role="tab" buttons. The tab
// role fits the button-based segmented-UI pattern and satisfies Biome's
// useSemanticElements rule. Scoping clicks through the tablist keeps
// these tests resilient to reset-button renames and unrelated buttons
// elsewhere on the page.

function clickThinking(mode: "off" | "adaptive" | "enabled") {
  const group = screen.getByRole("tablist", { name: "Thinking mode" });
  fireEvent.click(within(group).getByRole("tab", { name: mode }));
}
function clickDisplay(mode: "summarized" | "omitted") {
  const group = screen.getByRole("tablist", { name: "Thinking display" });
  fireEvent.click(within(group).getByRole("tab", { name: mode }));
}
function clickEffort(label: "—" | "low" | "med" | "high" | "max") {
  const group = screen.getByRole("tablist", { name: "Output effort" });
  fireEvent.click(within(group).getByRole("tab", { name: label }));
}

// ── Render ───────────────────────────────────────────────────────────

describe("SamplingSection — render", () => {
  it("renders current sampling values from props", () => {
    renderSection({ sampling: { max_tokens: 2048, temperature: 0.9 } });

    expect(screen.getByLabelText("Max tokens")).toHaveValue(2048);
    expect(screen.getByLabelText("Temperature")).toHaveValue(0.9);
  });

  it("renders empty string for null numeric fields", () => {
    renderSection({ sampling: { temperature: null, top_p: null, top_k: null } });

    expect(screen.getByLabelText("Temperature")).toHaveValue(null);
    expect(screen.getByLabelText("Top P")).toHaveValue(null);
    expect(screen.getByLabelText("Top K")).toHaveValue(null);
  });

  it("joins stop_sequences with commas for display", () => {
    renderSection({ sampling: { stop_sequences: ["END", "STOP"] } });

    expect(screen.getByLabelText("Stop sequences")).toHaveValue("END, STOP");
  });

  it("THINKING segment shows 'off' selected when provider_extras has no thinking key", () => {
    renderSection();
    const group = screen.getByRole("tablist", { name: "Thinking mode" });
    expect(within(group).getByRole("tab", { name: "off" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("THINKING segment shows 'enabled' selected when thinking.type is enabled", () => {
    renderSection({
      providerExtras: { thinking: { type: "enabled", budget_tokens: 8000 } },
    });
    const group = screen.getByRole("tablist", { name: "Thinking mode" });
    expect(within(group).getByRole("tab", { name: "enabled" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("THINKING segment shows 'adaptive' selected when thinking.type is adaptive", () => {
    renderSection({
      providerExtras: { thinking: { type: "adaptive" } },
    });
    const group = screen.getByRole("tablist", { name: "Thinking mode" });
    expect(within(group).getByRole("tab", { name: "adaptive" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("BUDGET shows the provider_extras.thinking.budget_tokens value", () => {
    renderSection({
      providerExtras: { thinking: { type: "enabled", budget_tokens: 8000 } },
    });
    expect(screen.getByLabelText("Budget")).toHaveValue(8000);
  });

  it("BUDGET is disabled when thinking mode is not enabled", () => {
    renderSection();
    expect(screen.getByLabelText("Budget")).toBeDisabled();
  });

  it("BUDGET is disabled when thinking is adaptive (no budget applies)", () => {
    renderSection({ providerExtras: { thinking: { type: "adaptive" } } });
    expect(screen.getByLabelText("Budget")).toBeDisabled();
  });

  it("DISPLAY defaults to 'summarized' when thinking.display is unset", () => {
    renderSection({
      providerExtras: { thinking: { type: "enabled", budget_tokens: 10000 } },
    });
    const group = screen.getByRole("tablist", { name: "Thinking display" });
    expect(within(group).getByRole("tab", { name: "summarized" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("DISPLAY shows 'omitted' when thinking.display is omitted", () => {
    renderSection({
      providerExtras: {
        thinking: { type: "enabled", budget_tokens: 10000, display: "omitted" },
      },
    });
    const group = screen.getByRole("tablist", { name: "Thinking display" });
    expect(within(group).getByRole("tab", { name: "omitted" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("EFFORT shows '—' selected when output_config.effort is unset", () => {
    renderSection();
    const group = screen.getByRole("tablist", { name: "Output effort" });
    expect(within(group).getByRole("tab", { name: "—" })).toHaveAttribute("aria-selected", "true");
  });

  it("EFFORT shows the set level when output_config.effort is present", () => {
    renderSection({ providerExtras: { output_config: { effort: "high" } } });
    const group = screen.getByRole("tablist", { name: "Output effort" });
    expect(within(group).getByRole("tab", { name: "high" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
});

// ── Modified indicator ───────────────────────────────────────────────

describe("SamplingSection — modified indicator", () => {
  it("shows section-level override chip when overrides include sampling_set", () => {
    renderSection({
      overrides: [{ kind: "sampling_set", target: "sampling:max_tokens", value: "2048" }],
    });

    expect(screen.getByText("1 override")).toBeInTheDocument();
  });

  it("pluralizes the section chip for 2+ overrides", () => {
    renderSection({
      overrides: [
        { kind: "sampling_set", target: "sampling:max_tokens", value: "2048" },
        { kind: "sampling_set", target: "sampling:temperature", value: "0.1" },
      ],
    });

    expect(screen.getByText("2 overrides")).toBeInTheDocument();
  });

  it("shows per-field reset button only for modified fields", () => {
    renderSection({
      overrides: [{ kind: "sampling_set", target: "sampling:temperature", value: "0.1" }],
    });

    const resetButtons = screen.getAllByRole("button", { name: "reset" });
    expect(resetButtons).toHaveLength(1);
  });

  it("counts provider_extras_set toward the section chip", () => {
    renderSection({
      overrides: [
        {
          kind: "provider_extras_set",
          target: "provider_extras:thinking",
          value: JSON.stringify({ type: "enabled", budget_tokens: 10000 }),
        },
      ],
    });

    expect(screen.getByText("1 override")).toBeInTheDocument();
  });

  it("counts nested display + effort overrides in the section chip", () => {
    renderSection({
      providerExtras: { thinking: { type: "enabled", budget_tokens: 10000 } },
      overrides: [
        {
          kind: "provider_extras_set",
          target: "provider_extras:thinking.display",
          value: '"omitted"',
        },
        {
          kind: "provider_extras_set",
          target: "provider_extras:output_config.effort",
          value: '"high"',
        },
      ],
    });

    expect(screen.getByText("2 overrides")).toBeInTheDocument();
  });
});

// ── Blur commits (sampling inputs) ───────────────────────────────────

describe("SamplingSection — blur commits", () => {
  it("commits max_tokens on blur when the value changes", () => {
    const { onOverride } = renderSection();
    const input = screen.getByLabelText("Max tokens");
    fireEvent.change(input, { target: { value: "2048" } });
    fireEvent.blur(input);

    expect(onOverride).toHaveBeenCalledWith([
      { kind: "sampling_set", target: "sampling:max_tokens", value: "2048" },
    ]);
  });

  it("clears max_tokens override on blur when edited back to original", () => {
    const { onOverride } = renderSection({ sampling: { max_tokens: 1024 } });
    const input = screen.getByLabelText("Max tokens");
    fireEvent.change(input, { target: { value: "4096" } });
    fireEvent.change(input, { target: { value: "1024" } });
    fireEvent.blur(input);

    expect(onOverride).toHaveBeenCalledWith([
      { kind: "sampling_set", target: "sampling:max_tokens", value: null },
    ]);
  });

  it("rejects non-numeric max_tokens by reverting local state", () => {
    const { onOverride } = renderSection({ sampling: { max_tokens: 1024 } });
    const input = screen.getByLabelText("Max tokens");
    fireEvent.change(input, { target: { value: "abc" } });
    fireEvent.blur(input);

    expect(onOverride).not.toHaveBeenCalled();
  });

  it("commits temperature as a JSON-encoded float on blur", () => {
    const { onOverride } = renderSection();
    const input = screen.getByLabelText("Temperature");
    fireEvent.change(input, { target: { value: "0.3" } });
    fireEvent.blur(input);

    expect(onOverride).toHaveBeenCalledWith([
      { kind: "sampling_set", target: "sampling:temperature", value: "0.3" },
    ]);
  });

  it("commits temperature=null (JSON null) when cleared to empty", () => {
    const { onOverride } = renderSection({ sampling: { temperature: 0.9 } });
    const input = screen.getByLabelText("Temperature");
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.blur(input);

    expect(onOverride).toHaveBeenCalledWith([
      { kind: "sampling_set", target: "sampling:temperature", value: "null" },
    ]);
  });

  it("commits top_k rounded to an int", () => {
    const { onOverride } = renderSection();
    const input = screen.getByLabelText("Top K");
    fireEvent.change(input, { target: { value: "40.7" } });
    fireEvent.blur(input);

    expect(onOverride).toHaveBeenCalledWith([
      { kind: "sampling_set", target: "sampling:top_k", value: "41" },
    ]);
  });

  it("commits stop_sequences as a JSON-encoded array on blur", () => {
    const { onOverride } = renderSection();
    const input = screen.getByLabelText("Stop sequences");
    fireEvent.change(input, { target: { value: "END, STOP, DONE" } });
    fireEvent.blur(input);

    expect(onOverride).toHaveBeenCalledWith([
      {
        kind: "sampling_set",
        target: "sampling:stop_sequences",
        value: JSON.stringify(["END", "STOP", "DONE"]),
      },
    ]);
  });

  it("commits stop_sequences back to empty [] when pristine was []", () => {
    const { onOverride } = renderSection({
      sampling: { stop_sequences: ["END"] },
      originalSampling: { stop_sequences: [] },
    });
    const input = screen.getByLabelText("Stop sequences");
    fireEvent.change(input, { target: { value: "" } });
    fireEvent.blur(input);

    // Edit back to original → value: null clears override.
    expect(onOverride).toHaveBeenCalledWith([
      { kind: "sampling_set", target: "sampling:stop_sequences", value: null },
    ]);
  });
});

// ── Reset buttons ────────────────────────────────────────────────────

describe("SamplingSection — reset buttons", () => {
  it("emits a null sampling override when a sampling reset is clicked", () => {
    const { onOverride } = renderSection({
      overrides: [{ kind: "sampling_set", target: "sampling:temperature", value: "0.1" }],
    });
    fireEvent.click(screen.getByRole("button", { name: "reset" }));

    expect(onOverride).toHaveBeenCalledWith([
      { kind: "sampling_set", target: "sampling:temperature", value: null },
    ]);
  });

  it("resets the thinking override when its reset is clicked", () => {
    const { onOverride } = renderSection({
      providerExtras: { thinking: { type: "enabled", budget_tokens: 10000 } },
      overrides: [
        {
          kind: "provider_extras_set",
          target: "provider_extras:thinking",
          value: JSON.stringify({ type: "enabled", budget_tokens: 10000 }),
        },
      ],
    });
    fireEvent.click(screen.getByRole("button", { name: "reset" }));

    expect(onOverride).toHaveBeenCalledWith([
      { kind: "provider_extras_set", target: "provider_extras:thinking", value: null },
    ]);
  });

  it("resets the display override when its reset is clicked", () => {
    const { onOverride } = renderSection({
      providerExtras: {
        thinking: { type: "enabled", budget_tokens: 10000, display: "omitted" },
      },
      overrides: [
        {
          kind: "provider_extras_set",
          target: "provider_extras:thinking.display",
          value: '"omitted"',
        },
      ],
    });
    fireEvent.click(screen.getByRole("button", { name: "reset" }));

    expect(onOverride).toHaveBeenCalledWith([
      { kind: "provider_extras_set", target: "provider_extras:thinking.display", value: null },
    ]);
  });

  it("resets the effort override when its reset is clicked", () => {
    const { onOverride } = renderSection({
      providerExtras: { output_config: { effort: "high" } },
      overrides: [
        {
          kind: "provider_extras_set",
          target: "provider_extras:output_config.effort",
          value: '"high"',
        },
      ],
    });
    fireEvent.click(screen.getByRole("button", { name: "reset" }));

    expect(onOverride).toHaveBeenCalledWith([
      { kind: "provider_extras_set", target: "provider_extras:output_config.effort", value: null },
    ]);
  });
});

// ── THINKING tri-state ───────────────────────────────────────────────

describe("SamplingSection — thinking mode transitions", () => {
  it("off → enabled writes compound batch with thinking payload + sampling locks", () => {
    const { onOverride } = renderSection({
      sampling: { temperature: 0.7, top_p: null, top_k: null },
      originalSampling: { temperature: 0.7, top_p: null, top_k: null },
    });
    clickThinking("enabled");

    expect(onOverride).toHaveBeenCalledTimes(1);
    const batch = onOverride.mock.calls[0]?.[0] as Override[];

    expect(batch[0]).toEqual({
      kind: "provider_extras_set",
      target: "provider_extras:thinking",
      value: JSON.stringify({ type: "enabled", budget_tokens: 10000 }),
    });
    // pristine temperature was 0.7 → JSON null to force-clear
    expect(batch).toContainEqual({
      kind: "sampling_set",
      target: "sampling:temperature",
      value: "null",
    });
    // pristine top_k/top_p were null → override-clear is enough
    expect(batch).toContainEqual({
      kind: "sampling_set",
      target: "sampling:top_k",
      value: null,
    });
    expect(batch).toContainEqual({
      kind: "sampling_set",
      target: "sampling:top_p",
      value: null,
    });
  });

  it("off → adaptive writes thinking={type:'adaptive'} with sampling locks", () => {
    const { onOverride } = renderSection({
      sampling: { temperature: null, top_p: null, top_k: null },
      originalSampling: { temperature: null, top_p: null, top_k: null },
    });
    clickThinking("adaptive");

    const batch = onOverride.mock.calls[0]?.[0] as Override[];
    expect(batch[0]).toEqual({
      kind: "provider_extras_set",
      target: "provider_extras:thinking",
      value: JSON.stringify({ type: "adaptive" }),
    });
    // All pristine-null sampling → clear-overrides suffice
    expect(batch).toContainEqual({
      kind: "sampling_set",
      target: "sampling:temperature",
      value: null,
    });
  });

  it("adaptive → enabled swaps payload without re-emitting sampling locks", () => {
    const { onOverride } = renderSection({
      providerExtras: { thinking: { type: "adaptive" } },
    });
    clickThinking("enabled");

    const batch = onOverride.mock.calls[0]?.[0] as Override[];
    // Only the thinking payload changes — no sampling_set entries, since
    // knobs are already locked from the previous active-mode write.
    expect(batch).toHaveLength(1);
    expect(batch[0]).toEqual({
      kind: "provider_extras_set",
      target: "provider_extras:thinking",
      value: JSON.stringify({ type: "enabled", budget_tokens: 10000 }),
    });
  });

  it("enabled → adaptive preserves budget reference but writes adaptive payload", () => {
    const { onOverride } = renderSection({
      providerExtras: { thinking: { type: "enabled", budget_tokens: 15000 } },
    });
    clickThinking("adaptive");

    const batch = onOverride.mock.calls[0]?.[0] as Override[];
    expect(batch).toHaveLength(1);
    expect(batch[0]).toEqual({
      kind: "provider_extras_set",
      target: "provider_extras:thinking",
      value: JSON.stringify({ type: "adaptive" }),
    });
  });

  it("enabled → off clears thinking + display nested + releases sampling locks", () => {
    const { onOverride } = renderSection({
      providerExtras: { thinking: { type: "enabled", budget_tokens: 8000 } },
      originalProviderExtras: {},
    });
    clickThinking("off");

    const batch = onOverride.mock.calls[0]?.[0] as Override[];

    // Pristine had no thinking → override-clear suffices for the flat key
    expect(batch[0]).toEqual({
      kind: "provider_extras_set",
      target: "provider_extras:thinking",
      value: null,
    });
    // Always clear the nested display override so it can't re-create
    // thinking via the dotted-path applier after the flat clear.
    expect(batch).toContainEqual({
      kind: "provider_extras_set",
      target: "provider_extras:thinking.display",
      value: null,
    });
    // Sampling locks released
    expect(batch).toContainEqual({
      kind: "sampling_set",
      target: "sampling:temperature",
      value: null,
    });
  });

  it("enabled → off with pristine-had-thinking writes JSON null for force-delete", () => {
    const { onOverride } = renderSection({
      providerExtras: { thinking: { type: "enabled", budget_tokens: 8000 } },
      originalProviderExtras: { thinking: { type: "enabled", budget_tokens: 8000 } },
    });
    clickThinking("off");

    const batch = onOverride.mock.calls[0]?.[0] as Override[];
    expect(batch[0]).toEqual({
      kind: "provider_extras_set",
      target: "provider_extras:thinking",
      value: "null",
    });
  });

  it("disables temp/top_k/top_p inputs when thinking is adaptive", () => {
    renderSection({ providerExtras: { thinking: { type: "adaptive" } } });

    expect(screen.getByLabelText("Temperature")).toBeDisabled();
    expect(screen.getByLabelText("Top K")).toBeDisabled();
    expect(screen.getByLabelText("Top P")).toBeDisabled();
  });

  it("disables temp/top_k/top_p inputs when thinking is enabled", () => {
    renderSection({
      providerExtras: { thinking: { type: "enabled", budget_tokens: 10000 } },
    });

    expect(screen.getByLabelText("Temperature")).toBeDisabled();
    expect(screen.getByLabelText("Top K")).toBeDisabled();
    expect(screen.getByLabelText("Top P")).toBeDisabled();
  });

  it("clicking the already-selected mode does nothing", () => {
    const { onOverride } = renderSection(); // thinking is off
    clickThinking("off");

    expect(onOverride).not.toHaveBeenCalled();
  });
});

// ── BUDGET ───────────────────────────────────────────────────────────

describe("SamplingSection — budget input", () => {
  it("commits a new budget as the full thinking payload on blur", () => {
    const { onOverride } = renderSection({
      providerExtras: { thinking: { type: "enabled", budget_tokens: 10000 } },
    });
    const input = screen.getByLabelText("Budget");
    fireEvent.change(input, { target: { value: "20000" } });
    fireEvent.blur(input);

    expect(onOverride).toHaveBeenCalledWith([
      {
        kind: "provider_extras_set",
        target: "provider_extras:thinking",
        value: JSON.stringify({ type: "enabled", budget_tokens: 20000 }),
      },
    ]);
  });

  it("rejects budgets below 1024 and reverts local state", () => {
    const { onOverride } = renderSection({
      providerExtras: { thinking: { type: "enabled", budget_tokens: 10000 } },
    });
    const input = screen.getByLabelText("Budget");
    fireEvent.change(input, { target: { value: "500" } });
    fireEvent.blur(input);

    expect(onOverride).not.toHaveBeenCalled();
    expect(input).toHaveValue(10000);
  });

  it("rejects non-numeric budget", () => {
    const { onOverride } = renderSection({
      providerExtras: { thinking: { type: "enabled", budget_tokens: 10000 } },
    });
    const input = screen.getByLabelText("Budget");
    fireEvent.change(input, { target: { value: "not-a-number" } });
    fireEvent.blur(input);

    expect(onOverride).not.toHaveBeenCalled();
  });

  it("clears override when budget is edited back to pristine enabled-budget", () => {
    const { onOverride } = renderSection({
      providerExtras: { thinking: { type: "enabled", budget_tokens: 20000 } },
      originalProviderExtras: { thinking: { type: "enabled", budget_tokens: 10000 } },
    });
    const input = screen.getByLabelText("Budget");
    fireEvent.change(input, { target: { value: "10000" } });
    fireEvent.blur(input);

    expect(onOverride).toHaveBeenCalledWith([
      { kind: "provider_extras_set", target: "provider_extras:thinking", value: null },
    ]);
  });
});

// ── DISPLAY ──────────────────────────────────────────────────────────

describe("SamplingSection — display segmented track", () => {
  it("writes nested display override when user picks 'omitted'", () => {
    const { onOverride } = renderSection({
      providerExtras: { thinking: { type: "enabled", budget_tokens: 10000 } },
    });
    clickDisplay("omitted");

    expect(onOverride).toHaveBeenCalledWith([
      {
        kind: "provider_extras_set",
        target: "provider_extras:thinking.display",
        value: '"omitted"',
      },
    ]);
  });

  it("clears the override when user picks the pristine display value", () => {
    // Pristine thinking has no display → default is "summarized"; user
    // had set omitted, now switches back to summarized. Match pristine →
    // override-clear.
    const { onOverride } = renderSection({
      providerExtras: {
        thinking: { type: "enabled", budget_tokens: 10000, display: "omitted" },
      },
      originalProviderExtras: { thinking: { type: "enabled", budget_tokens: 10000 } },
    });
    clickDisplay("summarized");

    expect(onOverride).toHaveBeenCalledWith([
      { kind: "provider_extras_set", target: "provider_extras:thinking.display", value: null },
    ]);
  });

  it("does not fire onOverride when clicking the currently-selected display", () => {
    const { onOverride } = renderSection({
      providerExtras: { thinking: { type: "enabled", budget_tokens: 10000 } },
    });
    clickDisplay("summarized"); // already the default-selected value

    expect(onOverride).not.toHaveBeenCalled();
  });

  it("disables all display segment buttons when thinking is off", () => {
    renderSection();
    const group = screen.getByRole("tablist", { name: "Thinking display" });
    for (const btn of within(group).getAllByRole("tab")) {
      expect(btn).toBeDisabled();
    }
  });
});

// ── EFFORT ───────────────────────────────────────────────────────────

describe("SamplingSection — effort segmented track", () => {
  it("writes effort override when user picks a level from —", () => {
    const { onOverride } = renderSection();
    clickEffort("high");

    expect(onOverride).toHaveBeenCalledWith([
      {
        kind: "provider_extras_set",
        target: "provider_extras:output_config.effort",
        value: '"high"',
      },
    ]);
  });

  it("writes 'med' as 'medium' in the override value (label/value mismatch intentional)", () => {
    const { onOverride } = renderSection();
    clickEffort("med");

    expect(onOverride).toHaveBeenCalledWith([
      {
        kind: "provider_extras_set",
        target: "provider_extras:output_config.effort",
        value: '"medium"',
      },
    ]);
  });

  it("clears the override when user picks — and pristine had no effort", () => {
    // Override was set to high; pristine had nothing. Picking — should
    // clear the override, not write an explicit JSON null.
    const { onOverride } = renderSection({
      providerExtras: { output_config: { effort: "high" } },
      overrides: [
        {
          kind: "provider_extras_set",
          target: "provider_extras:output_config.effort",
          value: '"high"',
        },
      ],
    });
    clickEffort("—");

    expect(onOverride).toHaveBeenCalledWith([
      { kind: "provider_extras_set", target: "provider_extras:output_config.effort", value: null },
    ]);
  });

  it("writes explicit JSON null when user picks — and pristine had an effort", () => {
    // Pristine had effort=low, user wants it off. Override-clear would
    // revert to pristine low, so we emit explicit null to force-delete
    // through the nested-clear backend path.
    const { onOverride } = renderSection({
      providerExtras: { output_config: { effort: "low" } },
      originalProviderExtras: { output_config: { effort: "low" } },
    });
    clickEffort("—");

    expect(onOverride).toHaveBeenCalledWith([
      {
        kind: "provider_extras_set",
        target: "provider_extras:output_config.effort",
        value: "null",
      },
    ]);
  });

  it("is independent of thinking state — remains active when thinking is off", () => {
    renderSection();
    const group = screen.getByRole("tablist", { name: "Output effort" });
    for (const btn of within(group).getAllByRole("tab")) {
      expect(btn).not.toBeDisabled();
    }
  });
});
