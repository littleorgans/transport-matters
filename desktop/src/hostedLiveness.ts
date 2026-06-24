import type { BrowserWindow } from "electron";

const HOSTED_BACKEND_FAILURE_LIMIT = 3;
const HOSTED_BACKEND_POLL_GAP_MS = 1_000;

export type HostedBackendHealthProbe = (healthUrl: string) => Promise<boolean>;

export function registerHostedBackendLivenessPoll(
  window: BrowserWindow,
  healthUrl: string,
  probeBackendHealth: HostedBackendHealthProbe,
  quitHostedApp: () => void,
): void {
  let consecutiveFailures = 0;
  let hasClosed = false;
  let hasLoaded = false;
  let pendingTimeout: ReturnType<typeof setTimeout> | undefined;

  const clearPendingTimeout = (): void => {
    if (pendingTimeout !== undefined) {
      clearTimeout(pendingTimeout);
      pendingTimeout = undefined;
    }
  };

  const scheduleNextProbe = (): void => {
    if (hasClosed) {
      return;
    }
    clearPendingTimeout();
    pendingTimeout = setTimeout(() => {
      pendingTimeout = undefined;
      void runProbe();
    }, HOSTED_BACKEND_POLL_GAP_MS);
  };

  const runProbe = async (): Promise<void> => {
    if (hasClosed) {
      return;
    }

    let isHealthy = false;
    try {
      isHealthy = await probeBackendHealth(healthUrl);
    } catch {
      isHealthy = false;
    }

    if (hasClosed) {
      return;
    }

    consecutiveFailures = isHealthy ? 0 : consecutiveFailures + 1;
    if (consecutiveFailures >= HOSTED_BACKEND_FAILURE_LIMIT) {
      quitHostedApp();
      return;
    }
    scheduleNextProbe();
  };

  window.webContents.on("did-finish-load", () => {
    if (hasLoaded) {
      return;
    }
    hasLoaded = true;
    void runProbe();
  });

  window.on("closed", () => {
    hasClosed = true;
    clearPendingTimeout();
  });
}
