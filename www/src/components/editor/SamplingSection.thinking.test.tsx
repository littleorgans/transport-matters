import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Override } from "../../types";
import { clickThinking, renderSection } from "./SamplingSection.testSupport";

describe("SamplingSection thinking mode transitions", () => {
  it("off to enabled writes compound batch with thinking payload and sampling locks", () => {
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

  it("off to adaptive writes thinking adaptive with sampling locks", () => {
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

  it("adaptive to enabled swaps payload without re-emitting sampling locks", () => {
    const { onOverride } = renderSection({
      providerExtras: { thinking: { type: "adaptive" } },
    });
    clickThinking("enabled");

    const batch = onOverride.mock.calls[0]?.[0] as Override[];
    // Only the thinking payload changes; no sampling_set entries, since
    // knobs are already locked from the previous active-mode write.
    expect(batch).toHaveLength(1);
    expect(batch[0]).toEqual({
      kind: "provider_extras_set",
      target: "provider_extras:thinking",
      value: JSON.stringify({ type: "enabled", budget_tokens: 10000 }),
    });
  });

  it("enabled to adaptive preserves budget reference but writes adaptive payload", () => {
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

  it("enabled to off clears thinking and releases sampling locks", () => {
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
    // Always clear the nested display override so it cannot re-create
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

  it("enabled to off with pristine thinking writes JSON null for force-delete", () => {
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

  it("disables temp top_k top_p inputs when thinking is adaptive", () => {
    renderSection({ providerExtras: { thinking: { type: "adaptive" } } });

    expect(screen.getByLabelText("Temperature")).toBeDisabled();
    expect(screen.getByLabelText("Top K")).toBeDisabled();
    expect(screen.getByLabelText("Top P")).toBeDisabled();
  });

  it("disables temp top_k top_p inputs when thinking is enabled", () => {
    renderSection({
      providerExtras: { thinking: { type: "enabled", budget_tokens: 10000 } },
    });

    expect(screen.getByLabelText("Temperature")).toBeDisabled();
    expect(screen.getByLabelText("Top K")).toBeDisabled();
    expect(screen.getByLabelText("Top P")).toBeDisabled();
  });

  it("clicking the already-selected mode does nothing", () => {
    const { onOverride } = renderSection();
    clickThinking("off");

    expect(onOverride).not.toHaveBeenCalled();
  });
});

describe("SamplingSection budget input", () => {
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
