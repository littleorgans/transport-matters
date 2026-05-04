import { EventEmitter } from "node:events";

import { describe, expect, it, vi } from "vitest";

import {
  BackendProcessExitError,
  buildBackendLaunch,
  launchBackendProcess,
  stopBackendProcess,
  watchBackendExitBeforeReady,
  type BackendChildProcess,
} from "./backendProcess.js";

class FakeChildProcess extends EventEmitter implements BackendChildProcess {
  killed = false;
  kill = vi.fn((signal?: NodeJS.Signals) => {
    this.killed = true;
    this.emit("exit", null, signal ?? null);
    return true;
  });
}

describe("backend process launch", () => {
  it("builds a claude CLI launch with pinned ports and environment", () => {
    const launch = buildBackendLaunch({
      client: "claude",
      env: {
        PATH: "/bin",
        TRANSPORT_MATTERS_PROXY_PORT: "old-proxy",
        TRANSPORT_MATTERS_WEB_PORT: "old-web",
      },
      proxyPort: 9900,
      webPort: 9901,
      workspaceDir: "/tmp/workspace",
    });

    expect(launch).toEqual({
      args: [
        "claude",
        "/tmp/workspace",
        "--web-port",
        "9901",
        "--proxy-port",
        "9900",
      ],
      command: "transport-matters",
      cwd: "/tmp/workspace",
      env: {
        PATH: "/bin",
        TRANSPORT_MATTERS_PROXY_PORT: "9900",
        TRANSPORT_MATTERS_WEB_PORT: "9901",
      },
    });
  });

  it("builds a codex CLI launch with the same pinned port contract", () => {
    const launch = buildBackendLaunch({
      client: "codex",
      env: {},
      proxyPort: 9902,
      webPort: 9903,
      workspaceDir: "/tmp/workspace",
    });

    expect(launch.args).toEqual([
      "codex",
      "/tmp/workspace",
      "--web-port",
      "9903",
      "--proxy-port",
      "9902",
    ]);
    expect(launch.env).toEqual({
      TRANSPORT_MATTERS_PROXY_PORT: "9902",
      TRANSPORT_MATTERS_WEB_PORT: "9903",
    });
  });

  it("spawns and terminates the backend child process", () => {
    const child = new FakeChildProcess();
    const spawnBackend = vi.fn(() => child);

    const backend = launchBackendProcess(
      {
        client: "claude",
        env: {},
        proxyPort: 9900,
        webPort: 9901,
        workspaceDir: "/tmp/workspace",
      },
      spawnBackend,
    );

    expect(spawnBackend).toHaveBeenCalledWith(
      "transport-matters",
      ["claude", "/tmp/workspace", "--web-port", "9901", "--proxy-port", "9900"],
      {
        cwd: "/tmp/workspace",
        env: {
          TRANSPORT_MATTERS_PROXY_PORT: "9900",
          TRANSPORT_MATTERS_WEB_PORT: "9901",
        },
        stdio: "pipe",
      },
    );

    stopBackendProcess(backend);

    expect(child.kill).toHaveBeenCalledWith("SIGTERM");
  });

  it("turns child exit before readiness into a clear error", async () => {
    const child = new FakeChildProcess();

    const watcher = watchBackendExitBeforeReady(child);
    child.emit("exit", 2, null);

    await expect(watcher.promise).rejects.toThrow(BackendProcessExitError);
    await expect(watcher.promise).rejects.toThrow(
      "Transport Matters backend exited before readiness with code 2.",
    );
  });
});
