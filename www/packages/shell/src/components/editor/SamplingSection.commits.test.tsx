import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderSection } from "./SamplingSection.testSupport";

describe("SamplingSection blur commits", () => {
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

    // Edit back to original → value: null clears override.
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

  it("commits temperature=null when cleared to empty", () => {
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

    expect(onOverride).toHaveBeenCalledWith([
      { kind: "sampling_set", target: "sampling:stop_sequences", value: null },
    ]);
  });
});
