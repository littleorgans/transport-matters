import { afterEach, describe, expect, it, vi } from "vitest";

import {
  BackendHealthTimeoutError,
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
});
