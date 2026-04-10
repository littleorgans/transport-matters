import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Rule } from "../types";
import { RulesList } from "./RulesList";

afterEach(cleanup);

function makeRule(overrides: Partial<Rule> = {}): Rule {
  return {
    id: "rule_abc123",
    name: "Strip MCP tools",
    enabled: true,
    scope: {
      global: true,
      session_id: null,
      device_id: null,
      account_id: null,
      model: null,
    },
    action: "strip_tools",
    params: { prefix: "mcp_" },
    created_at: "2025-06-01T00:00:00Z",
    applied_count: 5,
    ...overrides,
  };
}

describe("RulesList", () => {
  it("renders list of rules with names", () => {
    const rules = [
      makeRule({ name: "Alpha Rule" }),
      makeRule({ id: "rule_xyz", name: "Beta Rule" }),
    ];
    render(<RulesList rules={rules} onToggle={() => {}} onDelete={() => {}} />);
    expect(screen.getByText("Alpha Rule")).toBeInTheDocument();
    expect(screen.getByText("Beta Rule")).toBeInTheDocument();
  });

  it("toggle calls onToggle", () => {
    const onToggle = vi.fn();
    const rule = makeRule({ id: "rule_1", name: "My Rule", enabled: true });
    render(<RulesList rules={[rule]} onToggle={onToggle} onDelete={() => {}} />);
    const checkbox = screen.getByRole("checkbox", { name: /Toggle My Rule/i });
    fireEvent.click(checkbox);
    expect(onToggle).toHaveBeenCalledWith("rule_1", false);
  });

  it("delete calls onDelete", () => {
    const onDelete = vi.fn();
    const rule = makeRule({ id: "rule_2", name: "Del Rule" });
    render(<RulesList rules={[rule]} onToggle={() => {}} onDelete={onDelete} />);
    const deleteBtn = screen.getByRole("button", { name: /Delete Del Rule/i });
    fireEvent.click(deleteBtn);
    expect(onDelete).toHaveBeenCalledWith("rule_2");
  });

  it("shows empty state when no rules", () => {
    render(<RulesList rules={[]} onToggle={() => {}} onDelete={() => {}} />);
    expect(screen.getByText("No rules configured")).toBeInTheDocument();
  });
});
