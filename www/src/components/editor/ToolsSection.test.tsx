import { render, screen } from "@testing-library/react";
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
    const onOverride = vi.fn();

    render(<ToolsSection tools={tools} overrides={[]} onOverride={onOverride} />);

    expect(screen.getByText("built-in")).toBeInTheDocument();
    expect(screen.getByText("server")).toBeInTheDocument();
    expect(
      screen.getAllByText((_, el) => el?.textContent?.trim() === "Tools · 3").length,
    ).toBeGreaterThan(0);
  });

  it("all tools start checked with no overrides", () => {
    const tools = [
      makeTool({ name: "bash", description: "Run bash" }),
      makeTool({ name: "grep", description: "Search files" }),
    ];
    const onOverride = vi.fn();

    render(<ToolsSection tools={tools} overrides={[]} onOverride={onOverride} />);

    const toggles = screen.getAllByRole("switch");
    const checked = toggles.filter((t) => t.getAttribute("aria-checked") === "true");
    expect(checked.length).toBeGreaterThanOrEqual(2);
  });
});
