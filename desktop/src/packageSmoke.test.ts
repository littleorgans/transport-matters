import { EventEmitter } from "node:events";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import {
  findPackagedExecutable,
  runPackagedAppSmoke,
} from "./packageSmoke.js";

describe("desktop package smoke", () => {
  it("exposes one command desktop dev and package smoke workflows", () => {
    const packageJson = JSON.parse(
      readFileSync(new URL("../package.json", import.meta.url), "utf8"),
    ) as { scripts: Record<string, string> };
    const justfile = readFileSync(
      new URL("../justfile", import.meta.url),
      "utf8",
    );

    expect(packageJson.scripts["electron:install"]).toBe(
      "node node_modules/electron/install.js",
    );
    expect(packageJson.scripts.dev).toBe(
      "pnpm build && pnpm electron:install && electron .",
    );
      expect(packageJson.scripts["package:smoke"]).toBe(
        "pnpm build && pnpm electron:install && node scripts/package-smoke-build.mjs && node dist/packageSmoke.js",
      );
    expect(justfile).toContain("dev:");
    expect(justfile).toContain("package-smoke:");
  });

  it("finds the packaged macOS executable", () => {
    const packageDir = join(
      tmpdir(),
      `transport-matters-package-${crypto.randomUUID()}`,
    );
    const executablePath = join(
      packageDir,
      "Transport Matters-darwin-arm64",
      "Transport Matters.app",
      "Contents",
      "MacOS",
      "Transport Matters",
    );
    mkdirSync(join(executablePath, ".."), { recursive: true });
    writeFileSync(executablePath, "");

    expect(findPackagedExecutable(packageDir, "darwin")).toBe(executablePath);
  });

  it("ignores nested macOS helper executables", () => {
    const packageDir = join(
      tmpdir(),
      `transport-matters-package-${crypto.randomUUID()}`,
    );
    const appRoot = join(
      packageDir,
      "Transport Matters-darwin-arm64",
      "Transport Matters.app",
      "Contents",
    );
    const helperPath = join(
      appRoot,
      "Frameworks",
      "Transport Matters Helper.app",
      "Contents",
      "MacOS",
      "Transport Matters Helper",
    );
    const executablePath = join(appRoot, "MacOS", "Transport Matters");
    mkdirSync(join(helperPath, ".."), { recursive: true });
    mkdirSync(join(executablePath, ".."), { recursive: true });
    writeFileSync(helperPath, "");
    writeFileSync(executablePath, "");

    expect(findPackagedExecutable(packageDir, "darwin")).toBe(executablePath);
  });

  it("runs the packaged executable until it writes smoke readiness", async () => {
    const packageDir = join(
      tmpdir(),
      `transport-matters-package-${crypto.randomUUID()}`,
    );
    const executablePath = join(packageDir, "Transport Matters-linux-x64");
    const markerPath = join(packageDir, "smoke.json");
    mkdirSync(packageDir, { recursive: true });
    writeFileSync(executablePath, "");

    const result = await runPackagedAppSmoke({
      markerPath,
      packageDir,
      platform: "linux",
      spawnExecutable: (command, _args, options) => {
        expect(command).toBe(executablePath);
        expect(options.env.TRANSPORT_MATTERS_DESKTOP_PACKAGE_SMOKE).toBe("1");
        expect(options.env.TRANSPORT_MATTERS_DESKTOP_SMOKE_FILE).toBe(
          markerPath,
        );

        const child = new EventEmitter();
        setImmediate(() => {
          writeFileSync(
            markerPath,
            JSON.stringify({ status: "main-window-created" }),
          );
          child.emit("exit", 0);
        });
        return child;
      },
      timeoutMs: 100,
    });

    expect(result.status).toBe("main-window-created");
  });
});
