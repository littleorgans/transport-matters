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
    const onOverride = vi.fn();

    render(<ToolsSection tools={tools} overrides={[]} onOverride={onOverride} />);

    expect(screen.getByText("built-in")).toBeInTheDocument();
    expect(screen.getByText("server")).toBeInTheDocument();
    expect(
      screen.getAllByText((_, el) => el?.textContent?.trim() === "Tools · 3").length,
    ).toBeGreaterThan(0);
  });

  it("groups render collapsed by default so tool rows are hidden", () => {
    const tools = [
      makeTool({ name: "bash", description: "Run bash" }),
      makeTool({ name: "grep", description: "Search files" }),
    ];
    const onOverride = vi.fn();

    render(<ToolsSection tools={tools} overrides={[]} onOverride={onOverride} />);

    // Collapsed: no row-level toggles are mounted, only bulk controls
    // from the section header and the group headers themselves.
    expect(screen.queryByRole("switch")).toBeNull();
    // Group header still surfaces the checked count so the user knows
    // nothing is disabled without expanding.
    expect(screen.getByText("2/2")).toBeInTheDocument();
  });

  it("all tools start checked with no overrides", () => {
    const tools = [
      makeTool({ name: "bash", description: "Run bash" }),
      makeTool({ name: "grep", description: "Search files" }),
    ];
    const onOverride = vi.fn();

    render(<ToolsSection tools={tools} overrides={[]} onOverride={onOverride} />);

    // Expand the single `built-in` group so per-row toggles mount.
    fireEvent.click(screen.getByRole("button", { name: "+" }));

    const toggles = screen.getAllByRole("switch");
    const checked = toggles.filter((t) => t.getAttribute("aria-checked") === "true");
    expect(checked.length).toBeGreaterThanOrEqual(2);
  });

  it("dims the group card when every tool in it is disabled", () => {
    // Two groups; only the `server` group is fully disabled. Mirrors
    // the per-tool `opacity-40` treatment at the group level so a
    // user scanning the list doesn't confuse 0/N with N/N.
    const tools = [
      makeTool({ name: "bash", description: "Run bash" }),
      makeTool({ name: "mcp__server__read", description: "Read" }),
      makeTool({ name: "mcp__server__write", description: "Write" }),
    ];
    const onOverride = vi.fn();

    render(
      <ToolsSection
        tools={tools}
        overrides={[
          { kind: "tool_toggle", target: "tool:mcp__server__read", value: false },
          { kind: "tool_toggle", target: "tool:mcp__server__write", value: false },
        ]}
        onOverride={onOverride}
      />,
    );

    expect(screen.getByTestId("tool-group-server")).toHaveClass("opacity-40");
    expect(screen.getByTestId("tool-group-built-in")).not.toHaveClass("opacity-40");
  });

  it("un-dims the group card when at least one tool is enabled", () => {
    // Only one of two tools disabled → group still has signal, should
    // read as active (no opacity-40) so a user can still see the 1/2
    // count without the whole row feeling muted.
    const tools = [
      makeTool({ name: "mcp__server__read", description: "Read" }),
      makeTool({ name: "mcp__server__write", description: "Write" }),
    ];
    const onOverride = vi.fn();

    render(
      <ToolsSection
        tools={tools}
        overrides={[{ kind: "tool_toggle", target: "tool:mcp__server__read", value: false }]}
        onOverride={onOverride}
      />,
    );

    expect(screen.getByTestId("tool-group-server")).not.toHaveClass("opacity-40");
  });
});
