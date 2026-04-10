import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ToolDef } from "../../types";
import { ToolsSection } from "./ToolsSection";

function makeTool(overrides: Partial<ToolDef> & { name: string }): ToolDef {
  return {
    description: "A test tool",
    input_schema: { type: "object", properties: {} },
    ...overrides,
  };
}

describe("ToolsSection", () => {
  it("renders tool groups correctly", () => {
    const tools = [
      makeTool({ name: "mcp__server__read_file", description: "Reads a file" }),
      makeTool({ name: "mcp__server__write_file", description: "Writes a file" }),
      makeTool({ name: "bash", description: "Run bash commands" }),
    ];
    const onChange = vi.fn();

    render(<ToolsSection tools={tools} onChange={onChange} />);

    expect(screen.getByText("Built-in")).toBeInTheDocument();
    expect(screen.getByText("mcp")).toBeInTheDocument();
    // Header renders "Tools · 3" with the count in a separate text node.
    expect(
      screen.getAllByText((_, el) => el?.textContent?.trim() === "Tools · 3").length,
    ).toBeGreaterThan(0);
  });

  it("uncheck removes tool from output", () => {
    const tools = [
      makeTool({ name: "bash", description: "Run bash" }),
      makeTool({ name: "grep", description: "Search files" }),
    ];
    const onChange = vi.fn();

    render(<ToolsSection tools={tools} onChange={onChange} />);

    // Each tool renders as a role="switch" toggle.
    const toggles = screen.getAllByRole("switch");
    const checked = toggles.filter((t) => t.getAttribute("aria-checked") === "true");
    expect(checked.length).toBeGreaterThanOrEqual(2);

    // Uncheck the first tool toggle.
    const firstToggle = checked[0];
    if (firstToggle) {
      fireEvent.click(firstToggle);
      expect(onChange).toHaveBeenCalled();
      const lastCall = onChange.mock.calls[onChange.mock.calls.length - 1];
      const result = lastCall?.[0] as ToolDef[];
      // One tool should be removed
      expect(result.length).toBe(1);
    }
  });
});
