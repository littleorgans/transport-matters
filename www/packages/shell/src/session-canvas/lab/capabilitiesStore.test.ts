import type { HarnessCapability } from "@tm/core/types/capabilities";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The store's only side effect is GET /api/capabilities via fetchCapabilities;
// mock that so the test controls install state without a server.
const fetchCapabilities = vi.hoisted(() => vi.fn());
vi.mock("@tm/core", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@tm/core")>()),
  fetchCapabilities,
}));

import {
  harnessInstalled,
  resetCapabilitiesStoreForTests,
  useCapabilitiesStore,
} from "./capabilitiesStore";

const state = useCapabilitiesStore.getState;

function capability(installed: boolean): HarnessCapability {
  return {
    installed,
    path: installed ? "/usr/local/bin/harness" : null,
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

  it("treats harnesses as available until a probe confirms otherwise (fail-open)", () => {
    expect(state().status).toBe("idle");
    expect(harnessInstalled(state(), "claude")).toBe(true);
    expect(harnessInstalled(state(), "codex")).toBe(true);
  });

  it("loads capabilities once and exposes per-harness install state", async () => {
    fetchCapabilities.mockResolvedValue({
      harnesses: { claude: capability(true), codex: capability(false) },
    });

    state().ensureLoaded();
    state().ensureLoaded(); // a second call while loading must not trigger a second fetch
    await vi.waitFor(() => expect(state().status).toBe("ready"));

    expect(fetchCapabilities).toHaveBeenCalledTimes(1);
    expect(harnessInstalled(state(), "claude")).toBe(true);
    expect(harnessInstalled(state(), "codex")).toBe(false);
  });

  it("does not re-fetch once loaded", async () => {
    fetchCapabilities.mockResolvedValue({
      harnesses: { claude: capability(true), codex: capability(true) },
    });
    state().ensureLoaded();
    await vi.waitFor(() => expect(state().status).toBe("ready"));

    state().ensureLoaded();
    expect(fetchCapabilities).toHaveBeenCalledTimes(1);
  });

  it("stays available when the probe fails (unreachable backend, e.g. dev server)", async () => {
    fetchCapabilities.mockRejectedValue(new Error("network down"));

    state().ensureLoaded();
    await vi.waitFor(() => expect(state().status).toBe("error"));

    // Fail-open: a failed probe must not hide the buttons (the dev-server regression).
    expect(harnessInstalled(state(), "claude")).toBe(true);
    expect(harnessInstalled(state(), "codex")).toBe(true);
  });
});
