import { beforeEach, describe, expect, it, vi } from "vitest";
import { FRONTEND_STORAGE_KEYS } from "../../stores/persistence";
import {
  createCapturedRunKey,
  resetCapturedRunStoreForTests,
  useCapturedRunStore,
} from "./capturedRunStore";

const { createCapturedRunMock, deleteRunMock } = vi.hoisted(() => ({
  createCapturedRunMock: vi.fn(),
  deleteRunMock: vi.fn(),
}));

vi.mock("../../api", () => ({
  createCapturedRun: createCapturedRunMock,
  deleteRun: deleteRunMock,
}));

function store() {
  return useCapturedRunStore.getState();
}

describe("createCapturedRunKey", () => {
  it("mints a unique key per call, namespaced by provider", () => {
    const first = createCapturedRunKey("claude");
    const second = createCapturedRunKey("claude");
    expect(first).not.toBe(second);
    expect(first.startsWith("claude:")).toBe(true);
    expect(createCapturedRunKey("codex").startsWith("codex:")).toBe(true);
  });
});

describe("capturedRunStore", () => {
  beforeEach(() => {
    localStorage.clear();
    resetCapturedRunStoreForTests();
    createCapturedRunMock.mockReset();
    deleteRunMock.mockReset();
  });

  it("spawns once and stores the run keyed by pane", async () => {
    createCapturedRunMock.mockResolvedValue("run-1");

    await expect(store().ensureRun("claude:k1", "claude")).resolves.toBe("run-1");

    expect(createCapturedRunMock).toHaveBeenCalledWith("claude", undefined);
    expect(store().runs["claude:k1"]).toEqual({ provider: "claude", runId: "run-1" });
  });

  it("keeps two same-provider panes on independent runs (no shared PTY)", async () => {
    createCapturedRunMock.mockResolvedValueOnce("run-1").mockResolvedValueOnce("run-2");

    await expect(store().ensureRun("claude:k1", "claude")).resolves.toBe("run-1");
    await expect(store().ensureRun("claude:k2", "claude")).resolves.toBe("run-2");

    expect(createCapturedRunMock).toHaveBeenCalledTimes(2);
    expect(store().runs["claude:k1"]?.runId).toBe("run-1");
    expect(store().runs["claude:k2"]?.runId).toBe("run-2");
  });

  it("reuses a persisted run for the same pane without spawning again", async () => {
    createCapturedRunMock.mockResolvedValue("run-1");
    await store().ensureRun("claude:k1", "claude");

    await expect(store().ensureRun("claude:k1", "claude")).resolves.toBe("run-1");
    expect(createCapturedRunMock).toHaveBeenCalledTimes(1);
  });

  it("dedupes concurrent spawns for the same pane to a single run", async () => {
    let resolve!: (id: string) => void;
    createCapturedRunMock.mockReturnValue(
      new Promise<string>((r) => {
        resolve = r;
      }),
    );

    const first = store().ensureRun("claude:k1", "claude");
    const second = store().ensureRun("claude:k1", "claude");
    resolve("run-1");

    expect(await first).toBe("run-1");
    expect(await second).toBe("run-1");
    expect(createCapturedRunMock).toHaveBeenCalledTimes(1);
  });

  it("clears the in-flight guard on spawn failure so a retry can spawn", async () => {
    createCapturedRunMock.mockRejectedValueOnce(new Error("boom"));

    await expect(store().ensureRun("claude:k1", "claude")).rejects.toThrow("boom");
    expect(store().runs["claude:k1"]).toBeUndefined();

    createCapturedRunMock.mockResolvedValueOnce("run-2");
    await expect(store().ensureRun("claude:k1", "claude")).resolves.toBe("run-2");
    expect(createCapturedRunMock).toHaveBeenCalledTimes(2);
  });

  it("persists runs to localStorage so a reload re-attaches", async () => {
    createCapturedRunMock.mockResolvedValue("run-1");
    await store().ensureRun("claude:k1", "claude");

    const raw = localStorage.getItem(FRONTEND_STORAGE_KEYS.capturedRunStore);
    expect(raw).not.toBeNull();
    expect(JSON.parse(raw as string).state.runs).toEqual({
      "claude:k1": { provider: "claude", runId: "run-1" },
    });
  });

  it("stopRun stops (DELETE) and forgets only that pane's established run", async () => {
    createCapturedRunMock.mockResolvedValueOnce("run-1").mockResolvedValueOnce("run-2");
    deleteRunMock.mockResolvedValue(undefined);
    await store().ensureRun("claude:k1", "claude");
    await store().ensureRun("claude:k2", "claude");

    store().stopRun("claude:k1");

    // Kill stops the run on the server so it leaves the director roster too.
    expect(deleteRunMock).toHaveBeenCalledWith("run-1");
    expect(deleteRunMock).toHaveBeenCalledTimes(1);
    expect(store().runs["claude:k1"]).toBeUndefined();
    expect(store().runs["claude:k2"]).toEqual({ provider: "claude", runId: "run-2" });
  });

  it("stopRun cancels an in-flight spawn: stops the just-born run and never persists it", async () => {
    let resolveSpawn!: (id: string) => void;
    createCapturedRunMock.mockReturnValue(
      new Promise<string>((r) => {
        resolveSpawn = r;
      }),
    );
    deleteRunMock.mockResolvedValue(undefined);

    const spawn = store().ensureRun("claude:k1", "claude"); // POST in-flight
    store().stopRun("claude:k1"); // killed mid-spawn (runs["claude:k1"] still absent)
    resolveSpawn("run-1"); // POST resolves AFTER the kill
    await spawn;

    expect(deleteRunMock).toHaveBeenCalledWith("run-1");
    expect(store().runs["claude:k1"]).toBeUndefined();
  });

  it("stopRun is a no-op when no run exists for the pane", () => {
    store().stopRun("claude:missing");
    expect(deleteRunMock).not.toHaveBeenCalled();
  });
});
