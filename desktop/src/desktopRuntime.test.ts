import { describe, expect, it, vi } from "vitest";
import type { DesktopChannelSpec } from "./env.js";
import {
  parseDesktopRuntimeStatus,
  readDesktopRuntimeStatus,
  reclaimDesktopRuntime,
} from "./desktopRuntime.js";

const stableSpec = {
  id: "stable",
} as DesktopChannelSpec;

describe("desktop runtime status reader", () => {
  it("parses the shared channel status JSON contract", () => {
    expect(
      parseDesktopRuntimeStatus(
        JSON.stringify({
          runtime: {
            channel: "stable",
            defaultRouteUrl: "http://127.0.0.1:9901/canvas",
            proxyPort: 9900,
            state: "live",
            webPort: 9901,
          },
        }),
      ),
    ).toEqual({
      channel: "stable",
      defaultRouteUrl: "http://127.0.0.1:9901/canvas",
      proxyPort: 9900,
      state: "live",
      webPort: 9901,
    });
  });

  it("reads channel status through the CLI bootstrap surface", () => {
    const runStatusCommand = vi.fn((_channel: string) =>
      JSON.stringify({
        runtime: {
          channel: "stable",
          defaultRouteUrl: null,
          proxyPort: 9900,
          state: "live",
          webPort: 9901,
        },
      }),
    );

    expect(
      readDesktopRuntimeStatus(
        stableSpec,
        { TRANSPORT_MATTERS_CHANNEL: "stable" },
        runStatusCommand,
      ),
    ).toEqual({
      channel: "stable",
      defaultRouteUrl: null,
      proxyPort: 9900,
      state: "live",
      webPort: 9901,
    });
    expect(runStatusCommand).toHaveBeenCalledWith("stable", {
      TRANSPORT_MATTERS_CHANNEL: "stable",
    });
  });

  it("falls back when discovery fails or returns another channel", () => {
    expect(
      readDesktopRuntimeStatus(stableSpec, {}, () => {
        throw new Error("not installed");
      }),
    ).toBeNull();

    expect(
      readDesktopRuntimeStatus(stableSpec, {}, () =>
        JSON.stringify({
          runtime: {
            channel: "preview",
            defaultRouteUrl: null,
            proxyPort: 8797,
            state: "live",
            webPort: 8798,
          },
        }),
      ),
    ).toBeNull();
  });

  it("reclaims through the hidden CLI bootstrap surface", () => {
    const runReclaimCommand = vi.fn();
    const env = { TRANSPORT_MATTERS_CHANNEL: "stable" };

    reclaimDesktopRuntime(stableSpec, env, "/tmp/workspace", runReclaimCommand);

    expect(runReclaimCommand).toHaveBeenCalledWith(
      "stable",
      "/tmp/workspace",
      env,
    );
  });
});
