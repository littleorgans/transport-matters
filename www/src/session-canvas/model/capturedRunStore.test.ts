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

    expect(createCapturedRunMock).toHaveBeenCalledWith("claude", undefined, true);
    expect(store().runs["claude:k1"]).toEqual({ provider: "claude", runId: "run-1" });
  });

  it("defaults OSC color replies on and stores explicit changes", () => {
    expect(store().oscColorReplies).toBe(true);

    store().setOscColorReplies(false);

    expect(store().oscColorReplies).toBe(false);
    expect(
      JSON.parse(localStorage.getItem(FRONTEND_STORAGE_KEYS.capturedRunStore) as string).state
        .oscColorReplies,
    ).toBe(false);
  });

  it("passes an explicit OSC color replies opt-out through to the spawn", async () => {
    createCapturedRunMock.mockResolvedValue("run-1");

    await store().ensureRun("claude:k1", "claude", undefined, false);

    expect(createCapturedRunMock).toHaveBeenCalledWith("claude", undefined, false);
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

  it("setMinimized flags an established run, and clears it again, persisting the docked state", () => {
    useCapturedRunStore.setState({ runs: { "claude:k1": { provider: "claude", runId: "run-1" } } });

    store().setMinimized("claude:k1", true);
    expect(store().runs["claude:k1"]).toEqual({
      provider: "claude",
      runId: "run-1",
      minimized: true,
    });
    // The flag rides on the persisted record, so a reload can dock the run instead of reopening it.
    expect(
      JSON.parse(localStorage.getItem(FRONTEND_STORAGE_KEYS.capturedRunStore) as string).state.runs[
        "claude:k1"
      ].minimized,
    ).toBe(true);

    // Restore is the inverse: clearing the flag so a reload after restore reopens the pane as active.
    store().setMinimized("claude:k1", false);
    expect(store().runs["claude:k1"]).toEqual({
      provider: "claude",
      runId: "run-1",
      minimized: false,
    });
  });

  it("setMinimized does nothing for an unknown key with no run and no in-flight spawn", () => {
    // No record AND no pending spawn => nothing to flag and nothing to defer to, so it is a genuine
    // no-op. (The mid-spawn case, where a spawn IS pending, defers the flag — covered separately.)
    store().setMinimized("claude:pending", true);
    expect(store().runs["claude:pending"]).toBeUndefined();
  });

  it("minimize during an in-flight spawn persists minimized on resolve so a reload docks it", async () => {
    // The blocker fix: a minimize that races the spawn has no record yet, so the flag is DEFERRED as
    // a minimize-intent and applied when the spawn resolves and persists the record. Without it, the
    // resolve would persist {provider, runId} with no flag and a reload would REOPEN, not dock.
    let resolveSpawn!: (id: string) => void;
    createCapturedRunMock.mockReturnValue(
      new Promise<string>((r) => {
        resolveSpawn = r;
      }),
    );

    const spawn = store().ensureRun("claude:k1", "claude"); // POST in-flight, no record yet
    store().setMinimized("claude:k1", true); // minimized mid-spawn -> deferred intent
    expect(store().runs["claude:k1"]).toBeUndefined(); // nothing persisted while spawning

    resolveSpawn("run-1");
    await spawn;

    expect(store().runs["claude:k1"]).toEqual({
      provider: "claude",
      runId: "run-1",
      minimized: true,
    });
  });

  it("close wins over a mid-spawn minimize for the same key (cancel + DELETE, not dock)", async () => {
    // A key can be cancelled OR minimize-pending, never both: when a close races the spawn after a
    // minimize, the cancel (DELETE, do-not-persist) takes precedence and the deferred minimize-intent
    // is dropped, so the run is stopped rather than persisted-and-docked.
    let resolveSpawn!: (id: string) => void;
    createCapturedRunMock.mockReturnValue(
      new Promise<string>((r) => {
        resolveSpawn = r;
      }),
    );
    deleteRunMock.mockResolvedValue(undefined);

    const spawn = store().ensureRun("claude:k1", "claude");
    store().setMinimized("claude:k1", true); // deferred minimize-intent
    store().stopRun("claude:k1"); // then closed mid-spawn: cancel must win
    resolveSpawn("run-1");
    await spawn;

    expect(deleteRunMock).toHaveBeenCalledWith("run-1");
    expect(store().runs["claude:k1"]).toBeUndefined();
  });

  it("restore during an in-flight spawn drops the deferred minimize-intent (reopens on resolve)", async () => {
    // minimize-then-restore before the spawn resolves clears the intent, so the record persists open
    // and a reload reopens it (not docked).
    let resolveSpawn!: (id: string) => void;
    createCapturedRunMock.mockReturnValue(
      new Promise<string>((r) => {
        resolveSpawn = r;
      }),
    );

    const spawn = store().ensureRun("claude:k1", "claude");
    store().setMinimized("claude:k1", true); // deferred intent
    store().setMinimized("claude:k1", false); // restored before resolve -> intent cleared
    resolveSpawn("run-1");
    await spawn;

    expect(store().runs["claude:k1"]).toEqual({ provider: "claude", runId: "run-1" });
  });

  it("migrates a pre-S2 (v2) persisted payload without dropping runs or breaking the dock", async () => {
    // Old data carries runs but no `minimized` field, stored at the prior version. The version bump
    // must migrate it cleanly: runs survive and, with no flag, each is treated as open on reload (the
    // S1 behavior) rather than lost or wrongly docked.
    localStorage.setItem(
      FRONTEND_STORAGE_KEYS.capturedRunStore,
      JSON.stringify({
        version: 2,
        state: { runs: { "claude:k1": { provider: "claude", runId: "run-1" } } },
      }),
    );

    await useCapturedRunStore.persist.rehydrate();

    expect(store().runs["claude:k1"]).toEqual({ provider: "claude", runId: "run-1" });
    expect(store().runs["claude:k1"]?.minimized).toBeUndefined();
    expect(store().oscColorReplies).toBe(true);
  });

  it("rehydrates the core OSC color replies toggle", async () => {
    localStorage.setItem(
      FRONTEND_STORAGE_KEYS.capturedRunStore,
      JSON.stringify({ version: 4, state: { runs: {}, oscColorReplies: false } }),
    );

    await useCapturedRunStore.persist.rehydrate();

    expect(store().oscColorReplies).toBe(false);
  });
});
