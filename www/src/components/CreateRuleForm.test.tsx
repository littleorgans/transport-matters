import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CreateRuleForm, formReducer, initialFormState } from "./CreateRuleForm";

// ── Reducer unit tests ────────────────────────────────────────────

describe("formReducer", () => {
  it("initial state", () => {
    expect(initialFormState.name).toBe("");
    expect(initialFormState.action).toBe("strip_tools");
    expect(initialFormState.isGlobal).toBe(true);
    expect(initialFormState.error).toBeNull();
    expect(initialFormState.submitting).toBe(false);
  });

  it("setName updates name", () => {
    const next = formReducer(initialFormState, { type: "setName", value: "my rule" });
    expect(next.name).toBe("my rule");
  });

  it("setAction updates action and resets paramsText to the example for that action", () => {
    const next = formReducer(initialFormState, { type: "setAction", value: "strip_thinking" });
    expect(next.action).toBe("strip_thinking");
    expect(next.paramsText).toBe("{}");
  });

  it("setIsGlobal toggles scope flag", () => {
    const next = formReducer(initialFormState, { type: "setIsGlobal", value: false });
    expect(next.isGlobal).toBe(false);
  });

  it("setError stores an error message", () => {
    const next = formReducer(initialFormState, { type: "setError", value: "oops" });
    expect(next.error).toBe("oops");
  });

  it("setSubmitting sets submitting flag", () => {
    const next = formReducer(initialFormState, { type: "setSubmitting", value: true });
    expect(next.submitting).toBe(true);
  });

  it("reset returns to initial state", () => {
    const dirty = {
      ...initialFormState,
      name: "dirty",
      error: "some error",
      submitting: true,
    };
    const next = formReducer(dirty, { type: "reset" });
    expect(next).toEqual(initialFormState);
  });
});

// ── Component integration tests ───────────────────────────────────

describe("CreateRuleForm — submit paths", () => {
  it("submit success: calls onCreated and resets form", async () => {
    const onCreated = vi.fn().mockResolvedValue(undefined);
    render(<CreateRuleForm onCreated={onCreated} />);

    fireEvent.change(screen.getByPlaceholderText("Rule name"), {
      target: { value: "my-rule" },
    });
    const form = screen.getByRole("button", { name: "Create Rule" }).closest("form");
    if (form) fireEvent.submit(form);

    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
    // After success the form resets — name input is empty again
    expect((screen.getByPlaceholderText("Rule name") as HTMLInputElement).value).toBe("");
  });

  it("submit failure: shows error and does not reset", async () => {
    const onCreated = vi.fn().mockRejectedValue(new Error("server error"));
    render(<CreateRuleForm onCreated={onCreated} />);

    fireEvent.change(screen.getByPlaceholderText("Rule name"), {
      target: { value: "bad-rule" },
    });
    const form = screen.getByRole("button", { name: "Create Rule" }).closest("form");
    if (form) fireEvent.submit(form);

    await waitFor(() => expect(screen.getByText("server error")).toBeInTheDocument());
    // Name is preserved after failure
    expect((screen.getByPlaceholderText("Rule name") as HTMLInputElement).value).toBe("bad-rule");
  });

  it("invalid JSON in params shows error without calling onCreated", async () => {
    const onCreated = vi.fn();
    render(<CreateRuleForm onCreated={onCreated} />);

    fireEvent.change(screen.getByPlaceholderText("Rule name"), {
      target: { value: "my-rule" },
    });
    // Target the textarea by its initial display value
    fireEvent.change(screen.getByDisplayValue('{"prefix": "mcp_"}'), {
      target: { value: "not-json" },
    });

    const form = screen.getByRole("button", { name: "Create Rule" }).closest("form");
    if (form) fireEvent.submit(form);

    await waitFor(() => expect(screen.getByText("Params must be valid JSON")).toBeInTheDocument());
    expect(onCreated).not.toHaveBeenCalled();
  });
});
