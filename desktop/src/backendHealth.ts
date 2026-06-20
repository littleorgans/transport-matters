export interface BackendHealthResponse {
  ok: boolean;
}

export type FetchBackendHealth = (
  url: string,
  init: { signal: AbortSignal },
) => Promise<BackendHealthResponse>;

export interface BackendHealthProbeOptions {
  fetchHealth?: FetchBackendHealth;
  timeoutMs?: number;
}

export interface BackendHealthOptions {
  fetchHealth?: FetchBackendHealth;
  intervalMs?: number;
  probeTimeoutMs?: number;
  timeoutMs?: number;
  webPort: number;
}

const DEFAULT_HEALTH_INTERVAL_MS = 250;
export const DEFAULT_HEALTH_PROBE_TIMEOUT_MS = 750;
const DEFAULT_HEALTH_TIMEOUT_MS = 15_000;

export class BackendHealthTimeoutError extends Error {
  constructor(healthUrl: string, timeoutMs: number) {
    super(
      `Transport Matters backend did not become healthy at ${healthUrl} within ${timeoutMs}ms.`,
    );
    this.name = "BackendHealthTimeoutError";
  }
}

export function backendHealthUrl(webPort: number): string {
  return `http://127.0.0.1:${webPort}/health`;
}

export async function waitForBackendHealth(
  options: BackendHealthOptions,
): Promise<void> {
  const fetchHealth = options.fetchHealth ?? fetch;
  const intervalMs = options.intervalMs ?? DEFAULT_HEALTH_INTERVAL_MS;
  const probeTimeoutMs =
    options.probeTimeoutMs ?? DEFAULT_HEALTH_PROBE_TIMEOUT_MS;
  const timeoutMs = options.timeoutMs ?? DEFAULT_HEALTH_TIMEOUT_MS;
  const healthUrl = backendHealthUrl(options.webPort);
  const deadline = Date.now() + timeoutMs;

  while (Date.now() <= deadline) {
    const remainingMs = Math.max(deadline - Date.now(), 0);
    if (
      await isBackendHealthy(healthUrl, {
        fetchHealth,
        timeoutMs: Math.min(probeTimeoutMs, remainingMs),
      })
    ) {
      return;
    }
    await sleep(Math.min(intervalMs, Math.max(deadline - Date.now(), 0)));
  }

  throw new BackendHealthTimeoutError(healthUrl, timeoutMs);
}

export async function isBackendHealthy(
  healthUrl: string,
  options: BackendHealthProbeOptions = {},
): Promise<boolean> {
  const fetchHealth = options.fetchHealth ?? fetch;
  const timeoutMs = options.timeoutMs ?? DEFAULT_HEALTH_PROBE_TIMEOUT_MS;
  const controller = new AbortController();
  const timeout = setTimeout(() => {
    controller.abort();
  }, timeoutMs);

  try {
    const response = await fetchHealth(healthUrl, { signal: controller.signal });
    return response.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timeout);
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}
