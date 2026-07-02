import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderSection } from "./SamplingSection.testSupport";

describe("SamplingSection reset buttons", () => {
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
