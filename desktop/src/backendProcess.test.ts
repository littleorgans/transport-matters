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
  it("builds the internal desktop backend launch with pinned ports and environment", () => {
    const launch = buildBackendLaunch({
      env: {
        PATH: "/bin",
        TRANSPORT_MATTERS_CHANNEL: "preview",
        TRANSPORT_MATTERS_CWD: "/old/workspace",
        TRANSPORT_MATTERS_PROXY_PORT: "old-proxy",
        TRANSPORT_MATTERS_WEB_PORT: "old-web",
      },
      proxyPort: 9900,
      webPort: 9901,
      workspaceDir: "/tmp/workspace",
    });

    expect(launch).toEqual({
      args: [
        "_desktop-backend",
        "--work-dir",
        "/tmp/workspace",
        "--web-port",
        "9901",
        "--proxy-port",
        "9900",
        "--channel",
        "preview",
      ],
      command: "transport-matters",
      cwd: "/tmp/workspace",
      env: {
        PATH: "/bin",
        TRANSPORT_MATTERS_CHANNEL: "preview",
        TRANSPORT_MATTERS_CWD: "/tmp/workspace",
        TRANSPORT_MATTERS_PROXY_PORT: "9900",
        TRANSPORT_MATTERS_WEB_PORT: "9901",
      },
    });
  });

  it("does not build provider CLI launches", () => {
    const launch = buildBackendLaunch({
      env: {},
      proxyPort: 9902,
      webPort: 9903,
      workspaceDir: "/tmp/workspace",
    });

    expect(launch.args).toEqual([
      "_desktop-backend",
      "--work-dir",
      "/tmp/workspace",
      "--web-port",
      "9903",
      "--proxy-port",
      "9902",
      "--channel",
      "stable",
    ]);
    expect(launch.env).toEqual({
      TRANSPORT_MATTERS_CHANNEL: "stable",
      TRANSPORT_MATTERS_CWD: "/tmp/workspace",
      TRANSPORT_MATTERS_PROXY_PORT: "9902",
      TRANSPORT_MATTERS_WEB_PORT: "9903",
    });
    expect(launch.args).not.toContain("claude");
    expect(launch.args).not.toContain("codex");
  });

  it("spawns and terminates the backend child process", () => {
    const child = new FakeChildProcess();
    const spawnBackend = vi.fn(() => child);

    const backend = launchBackendProcess(
      {
        env: {},
        proxyPort: 9900,
        webPort: 9901,
        workspaceDir: "/tmp/workspace",
      },
      spawnBackend,
    );

    expect(spawnBackend).toHaveBeenCalledWith(
      "transport-matters",
      [
        "_desktop-backend",
        "--work-dir",
        "/tmp/workspace",
        "--web-port",
        "9901",
        "--proxy-port",
        "9900",
        "--channel",
        "stable",
      ],
      {
        cwd: "/tmp/workspace",
        env: {
          TRANSPORT_MATTERS_CHANNEL: "stable",
          TRANSPORT_MATTERS_CWD: "/tmp/workspace",
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
