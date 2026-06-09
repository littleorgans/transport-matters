import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { CliCapability, CliName } from "../../types";
import { CanvasLabRoute } from "./CanvasLabRoute";
import { resetCanvasLabStoreForTests } from "./canvasLabStore";
import { resetCapabilitiesStoreForTests, useCapabilitiesStore } from "./capabilitiesStore";

// The lab gates its captured-run spawn buttons on managed-CLI availability. Seeding
// the capabilities store to "ready" makes CanvasLabRoute's mount-time probe a no-op,
// so these tests drive button visibility directly off install state with no network.

function capability(installed: boolean): CliCapability {
  return {
    installed,
    path: installed ? "/usr/local/bin/cli" : null,
    version: installed ? "1.0.0" : null,
  };
}

function seedCapabilities(installed: Record<CliName, boolean>): void {
  useCapabilitiesStore.setState({
    status: "ready",
    clis: { claude: capability(installed.claude), codex: capability(installed.codex) },
  });
}

describe("CanvasLabRoute captured-run spawn buttons", () => {
  beforeEach(() => {
    resetCanvasLabStoreForTests();
    resetCapabilitiesStoreForTests();
  });

  afterEach(() => {
    resetCanvasLabStoreForTests();
    resetCapabilitiesStoreForTests();
  });

  it("shows both spawn buttons when both CLIs are installed", () => {
    seedCapabilities({ claude: true, codex: true });
    render(<CanvasLabRoute />);
    expect(screen.getByRole("button", { name: "Spawn Claude" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Spawn Codex" })).toBeInTheDocument();
  });

  it("hides the codex button when codex is not installed", () => {
    seedCapabilities({ claude: true, codex: false });
    render(<CanvasLabRoute />);
    expect(screen.getByRole("button", { name: "Spawn Claude" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Spawn Codex" })).not.toBeInTheDocument();
  });

  it("hides the claude button when claude is not installed", () => {
    seedCapabilities({ claude: false, codex: true });
    render(<CanvasLabRoute />);
    expect(screen.queryByRole("button", { name: "Spawn Claude" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Spawn Codex" })).toBeInTheDocument();
  });

  it("hides both spawn buttons when neither CLI is installed", () => {
    seedCapabilities({ claude: false, codex: false });
    render(<CanvasLabRoute />);
    expect(screen.queryByRole("button", { name: "Spawn Claude" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Spawn Codex" })).not.toBeInTheDocument();
  });
});
