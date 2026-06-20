import { homedir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";
import { resolveDesktopChannelSpec } from "./env.js";

describe("desktop channel environment", () => {
  it("resolves the stable desktop channel by default", () => {
    const spec = resolveDesktopChannelSpec({});

    expect(spec).toMatchObject({
      badge: null,
      databaseName: "transport_matters",
      home: join(homedir(), ".transport-matters"),
      id: "stable",
      label: "Stable",
      proxyPort: 8787,
      webPort: 8788,
      electron: {
        appId: "io.helioy.transport-matters",
        appName: "Transport Matters",
        dockIcon: "default",
        userDataDir: null,
      },
    });
  });

  it("resolves the preview desktop channel from the environment", () => {
    const spec = resolveDesktopChannelSpec({
      TRANSPORT_MATTERS_CHANNEL: "preview",
    });

    expect(spec).toMatchObject({
      badge: { color: "amber", hex: "#f59e0b", text: "PREVIEW" },
      databaseName: "transport_matters_preview",
      home: join(homedir(), ".transport-matters-preview"),
      id: "preview",
      label: "Preview",
      proxyPort: 8797,
      webPort: 8798,
      electron: {
        appId: "io.helioy.transport-matters.preview",
        appName: "Transport Matters Preview",
        dockIcon: "preview-amber",
        userDataDir: "electron-user-data",
      },
    });
  });
});
