import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { SamplingParams } from "../../types";
import { SamplingSection } from "./SamplingSection";
import { renderSection } from "./SamplingSection.testSupport";

const BASE_SAMPLING: SamplingParams = {
  max_tokens: 1024,
  temperature: 0.7,
  top_p: null,
  top_k: null,
  stop_sequences: [],
};

describe("SamplingSection render", () => {
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

  it("resets stop sequence edits when upstream arrays have the same joined text", () => {
    const onOverride = vi.fn();
    const props = {
      originalSampling: BASE_SAMPLING,
      providerExtras: {},
      originalProviderExtras: {},
      overrides: [],
      onOverride,
    };
    const { rerender } = render(
      <SamplingSection {...props} sampling={{ ...BASE_SAMPLING, stop_sequences: ["a", "b"] }} />,
    );

    const input = screen.getByLabelText("Stop sequences");
    fireEvent.change(input, { target: { value: "dirty" } });

    rerender(
      <SamplingSection {...props} sampling={{ ...BASE_SAMPLING, stop_sequences: ["a, b"] }} />,
    );

    expect(input).toHaveValue("a, b");
  });

  it("shows off selected when provider_extras has no thinking key", () => {
    renderSection();
    const group = screen.getByRole("tablist", { name: "Thinking mode" });
    expect(within(group).getByRole("tab", { name: "off" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("shows enabled selected when thinking.type is enabled", () => {
    renderSection({
      providerExtras: { thinking: { type: "enabled", budget_tokens: 8000 } },
    });
    const group = screen.getByRole("tablist", { name: "Thinking mode" });
    expect(within(group).getByRole("tab", { name: "enabled" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("shows adaptive selected when thinking.type is adaptive", () => {
    renderSection({
      providerExtras: { thinking: { type: "adaptive" } },
    });
    const group = screen.getByRole("tablist", { name: "Thinking mode" });
    expect(within(group).getByRole("tab", { name: "adaptive" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("shows the provider_extras.thinking.budget_tokens value", () => {
    renderSection({
      providerExtras: { thinking: { type: "enabled", budget_tokens: 8000 } },
    });
    expect(screen.getByLabelText("Budget")).toHaveValue(8000);
  });

  it("disables budget when thinking mode is not enabled", () => {
    renderSection();
    expect(screen.getByLabelText("Budget")).toBeDisabled();
  });

  it("disables budget when thinking is adaptive", () => {
    renderSection({ providerExtras: { thinking: { type: "adaptive" } } });
    expect(screen.getByLabelText("Budget")).toBeDisabled();
  });

  it("defaults display to summarized when thinking.display is unset", () => {
    renderSection({
      providerExtras: { thinking: { type: "enabled", budget_tokens: 10000 } },
    });
    const group = screen.getByRole("tablist", { name: "Thinking display" });
    expect(within(group).getByRole("tab", { name: "summarized" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("shows omitted when thinking.display is omitted", () => {
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

  it("shows no output effort selected when output_config.effort is unset", () => {
    renderSection();
    const group = screen.getByRole("tablist", { name: "Output effort" });
    expect(within(group).getByRole("tab", { name: "—" })).toHaveAttribute("aria-selected", "true");
  });

  it("shows the set output effort level when output_config.effort is present", () => {
    renderSection({ providerExtras: { output_config: { effort: "high" } } });
    const group = screen.getByRole("tablist", { name: "Output effort" });
    expect(within(group).getByRole("tab", { name: "high" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

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

  it("counts nested display and effort overrides in the section chip", () => {
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
