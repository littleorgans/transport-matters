import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CliCapability } from "../../types";

// The store's only side effect is GET /api/capabilities via fetchCapabilities;
// mock that so the test controls install state without a server.
const fetchCapabilities = vi.hoisted(() => vi.fn());
vi.mock("../../api", () => ({ fetchCapabilities }));

import {
  cliInstalled,
  resetCapabilitiesStoreForTests,
  useCapabilitiesStore,
} from "./capabilitiesStore";

const state = useCapabilitiesStore.getState;

function capability(installed: boolean): CliCapability {
  return {
    installed,
    path: installed ? "/usr/local/bin/cli" : null,
    version: installed ? "1.0.0" : null,
  };
}

describe("capabilitiesStore", () => {
  beforeEach(() => {
    resetCapabilitiesStoreForTests();
    fetchCapabilities.mockReset();
  });

  afterEach(() => {
    resetCapabilitiesStoreForTests();
  });

  it("reports nothing installed until a probe lands", () => {
    expect(state().status).toBe("idle");
    expect(cliInstalled(state(), "claude")).toBe(false);
    expect(cliInstalled(state(), "codex")).toBe(false);
  });

  it("loads capabilities once and exposes per-CLI install state", async () => {
    fetchCapabilities.mockResolvedValue({
      clis: { claude: capability(true), codex: capability(false) },
    });

    state().ensureLoaded();
    state().ensureLoaded(); // a second call while loading must not trigger a second fetch
    await vi.waitFor(() => expect(state().status).toBe("ready"));

    expect(fetchCapabilities).toHaveBeenCalledTimes(1);
    expect(cliInstalled(state(), "claude")).toBe(true);
    expect(cliInstalled(state(), "codex")).toBe(false);
  });

  it("does not re-fetch once loaded", async () => {
    fetchCapabilities.mockResolvedValue({
      clis: { claude: capability(true), codex: capability(true) },
    });
    state().ensureLoaded();
    await vi.waitFor(() => expect(state().status).toBe("ready"));

    state().ensureLoaded();
    expect(fetchCapabilities).toHaveBeenCalledTimes(1);
  });

  it("stays not-installed when the probe fails", async () => {
    fetchCapabilities.mockRejectedValue(new Error("network down"));

    state().ensureLoaded();
    await vi.waitFor(() => expect(state().status).toBe("error"));

    expect(cliInstalled(state(), "claude")).toBe(false);
    expect(cliInstalled(state(), "codex")).toBe(false);
  });
});
