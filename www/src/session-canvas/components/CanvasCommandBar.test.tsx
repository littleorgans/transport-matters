import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { CliName } from "../../types";
import type { CanvasLaunchContext } from "../route";
import { CanvasCommandBar } from "./CanvasCommandBar";

const launch = {
  owner: "local",
  workspaceHash: "hash-1",
  cli: null,
  runId: null,
} satisfies CanvasLaunchContext;

function setup() {
  const onSpawnCapturedRun = vi.fn<(provider: CliName) => void>();
  render(
    <CanvasCommandBar
      focusedTitle={null}
      launch={launch}
      onFocusPicker={vi.fn()}
      onResetViewport={vi.fn()}
      onSpawnCapturedRun={onSpawnCapturedRun}
    />,
  );
  return { onSpawnCapturedRun };
}

describe("CanvasCommandBar", () => {
  it("calls onSpawnCapturedRun with the selected provider", () => {
    const { onSpawnCapturedRun } = setup();

    fireEvent.click(screen.getByRole("button", { name: "Spawn Claude" }));
    fireEvent.click(screen.getByRole("button", { name: "Spawn Codex" }));

    expect(onSpawnCapturedRun).toHaveBeenNthCalledWith(1, "claude");
    expect(onSpawnCapturedRun).toHaveBeenNthCalledWith(2, "codex");
  });

  it("renders labelled keyboard focusable spawn buttons", () => {
    setup();

    const claudeButton = screen.getByRole("button", { name: "Spawn Claude" });
    const codexButton = screen.getByRole("button", { name: "Spawn Codex" });

    expect(claudeButton).toHaveAttribute("type", "button");
    expect(codexButton).toHaveAttribute("type", "button");

    claudeButton.focus();
    expect(claudeButton).toHaveFocus();

    codexButton.focus();
    expect(codexButton).toHaveFocus();
  });
});
