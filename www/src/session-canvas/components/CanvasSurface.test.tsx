import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { PaneId } from "../../engine";
import type { CliName } from "../../types";
import { resetCanvasStoreForTests, useCanvasStore } from "../model/canvasStore";
import type { CanvasLaunchContext } from "../route";
import {
  installMockTransport,
  jsonResponse,
  renderWithQuery,
  restoreTransport,
} from "../testUtils";
import { CanvasSurface } from "./CanvasSurface";

vi.mock("../../ambient/createAmbientBackground");

const launch = {
  owner: "local",
  workspaceHash: "hash-1",
  cli: null,
  runId: null,
} satisfies CanvasLaunchContext;

describe("CanvasSurface", () => {
  afterEach(() => {
    resetCanvasStoreForTests();
    restoreTransport();
    vi.restoreAllMocks();
  });

  it("wires command bar captured run actions to addCapturedRun", () => {
    resetCanvasStoreForTests(launch);
    installMockTransport(() => jsonResponse({ items: [], nextCursor: null }));
    const addCapturedRun = vi.fn((provider: CliName): PaneId => `captured:${provider}`);
    useCanvasStore.setState({ addCapturedRun });

    renderWithQuery(
      <CanvasSurface launch={launch} launchSessionId={null} launchStatus="resolved" />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Spawn Codex" }));

    expect(addCapturedRun).toHaveBeenCalledWith("codex");
  });
});
