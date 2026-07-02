import { describe, expect, it } from "vitest";
import {
  buildDevServerProxy,
  DEV_API_BASE_URL_ENV,
  resolveDevApiProxyTarget,
} from "../vite.config";

describe("Vite dev API proxy", () => {
  it("reads the dev API target from the runtime environment", () => {
    expect(
      resolveDevApiProxyTarget({
        [DEV_API_BASE_URL_ENV]: "http://127.0.0.1:9901/canvas",
      }),
    ).toBe("http://127.0.0.1:9901");

    expect(
      buildDevServerProxy({
        [DEV_API_BASE_URL_ENV]: "http://127.0.0.1:9901",
      }),
    ).toEqual({
      "/api": {
        changeOrigin: true,
        target: "http://127.0.0.1:9901",
        ws: true,
      },
    });
  });

  it("does not install a fixed-port proxy fallback", () => {
    expect(resolveDevApiProxyTarget({})).toBeUndefined();
    expect(buildDevServerProxy({})).toBeUndefined();
  });
});
