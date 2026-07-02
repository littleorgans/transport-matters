import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { clickDisplay, clickEffort, renderSection } from "./SamplingSection.testSupport";

describe("SamplingSection display segmented track", () => {
  it("writes nested display override when user picks omitted", () => {
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
    clickDisplay("summarized");

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

describe("SamplingSection effort segmented track", () => {
  it("writes effort override when user picks a level from unset", () => {
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

  it("writes med as medium in the override value", () => {
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

  it("clears the override when user picks unset and pristine had no effort", () => {
    // Override was set to high; pristine had nothing. Picking unset should
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

  it("writes explicit JSON null when user picks unset and pristine had an effort", () => {
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

  it("is independent of thinking state and remains active when thinking is off", () => {
    renderSection();
    const group = screen.getByRole("tablist", { name: "Output effort" });
    for (const btn of within(group).getAllByRole("tab")) {
      expect(btn).not.toBeDisabled();
    }
  });
});
