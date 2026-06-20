import { afterEach, describe, expect, it, vi } from "vitest";

import {
  BackendHealthTimeoutError,
  isBackendHealthy,
  waitForBackendHealth,
} from "./backendHealth.js";

describe("backend health polling", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("polls /health on the selected web port until the backend is ready", async () => {
    const fetchHealth = vi
      .fn()
      .mockResolvedValueOnce({ ok: false })
      .mockResolvedValueOnce({ ok: true });

    await waitForBackendHealth({
      fetchHealth,
      intervalMs: 1,
      timeoutMs: 50,
      webPort: 9901,
    });

    expect(fetchHealth).toHaveBeenCalledTimes(2);
    expect(fetchHealth).toHaveBeenCalledWith("http://127.0.0.1:9901/health", {
      signal: expect.any(AbortSignal),
    });
  });

  it("reports a timeout when /health never becomes ready", async () => {
    vi.useFakeTimers();
    const fetchHealth = vi.fn().mockResolvedValue({ ok: false });

    const pending = waitForBackendHealth({
      fetchHealth,
      intervalMs: 5,
      timeoutMs: 10,
      webPort: 9901,
    });
    const handled = pending.catch((error: unknown) => error);

    await vi.advanceTimersByTimeAsync(15);

    const error = await handled;
    expect(error).toBeInstanceOf(BackendHealthTimeoutError);
    expect(error).toEqual(
      new BackendHealthTimeoutError("http://127.0.0.1:9901/health", 10),
    );
  });

  it("aborts a stalled health probe after its per-probe timeout", async () => {
    vi.useFakeTimers();
    let capturedSignal: AbortSignal | undefined;
    const fetchHealth = vi.fn(
      (_url: string, init: { signal: AbortSignal }) =>
        new Promise<{ ok: boolean }>((resolve) => {
          capturedSignal = init.signal;
          init.signal.addEventListener("abort", () => {
            resolve({ ok: false });
          });
        }),
    );

    const pending = isBackendHealthy("http://127.0.0.1:9901/health", {
      fetchHealth,
      timeoutMs: 25,
    });

    await vi.advanceTimersByTimeAsync(25);

    await expect(pending).resolves.toBe(false);
    expect(capturedSignal?.aborted).toBe(true);
  });

  it("clears the per-probe timeout when a health probe settles", async () => {
    vi.useFakeTimers();
    let capturedSignal: AbortSignal | undefined;
    const fetchHealth = vi.fn(
      async (_url: string, init: { signal: AbortSignal }) => {
        capturedSignal = init.signal;
        return { ok: true };
      },
    );

    await expect(
      isBackendHealthy("http://127.0.0.1:9901/health", {
        fetchHealth,
        timeoutMs: 25,
      }),
    ).resolves.toBe(true);
    await vi.advanceTimersByTimeAsync(25);

    expect(capturedSignal?.aborted).toBe(false);
  });
});
