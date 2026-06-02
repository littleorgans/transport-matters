import { spawn as spawnChildProcess } from "node:child_process";
import type { SpawnOptions } from "node:child_process";
import {
  existsSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import type { EventEmitter } from "node:events";
import { ENV } from "./env.js";

export interface PackageSmokeResult {
  executablePath: string;
  status: "main-window-created";
}

export interface PackageSmokeOptions {
  env?: NodeJS.ProcessEnv;
  markerPath?: string;
  packageDir?: string;
  platform?: NodeJS.Platform;
  spawnExecutable?: SpawnPackagedExecutable;
  timeoutMs?: number;
}

export type PackagedChildProcess = Pick<EventEmitter, "once"> & {
  kill?: (signal?: NodeJS.Signals) => boolean;
};

export type SpawnPackagedExecutable = (
  command: string,
  args: string[],
  options: SpawnOptions & { env: NodeJS.ProcessEnv },
) => PackagedChildProcess;

const DEFAULT_TIMEOUT_MS = 15_000;

export async function runPackagedAppSmoke(
  options: PackageSmokeOptions = {},
): Promise<PackageSmokeResult> {
  const packageDir = options.packageDir ?? defaultPackageDir();
  const platform = options.platform ?? process.platform;
  const executablePath = findPackagedExecutable(packageDir, platform);
  const markerPath = options.markerPath ?? createMarkerPath();
  const spawnExecutable = options.spawnExecutable ?? spawnChildProcess;

  rmSync(markerPath, { force: true });
  const child = spawnExecutable(executablePath, [], {
    env: buildSmokeEnv(options.env ?? process.env, markerPath),
    stdio: "inherit",
  });

  await waitForExit(child, options.timeoutMs ?? DEFAULT_TIMEOUT_MS);

  return {
    executablePath,
    status: readSmokeStatus(markerPath),
  };
}

export function findPackagedExecutable(
  packageDir: string,
  platform: NodeJS.Platform = process.platform,
): string {
  if (platform === "darwin") {
    return findDarwinExecutable(packageDir);
  }

  const candidates = findFiles(packageDir);
  const executable = candidates.find((candidate) =>
    platform === "win32"
      ? candidate.endsWith(".exe")
      : basename(candidate).startsWith("Transport Matters"),
  );

  if (executable === undefined) {
    throw new Error(`No packaged desktop executable found in ${packageDir}.`);
  }
  return executable;
}

function buildSmokeEnv(
  env: NodeJS.ProcessEnv,
  markerPath: string,
): NodeJS.ProcessEnv {
  return {
    ...env,
    [ENV.DESKTOP_PACKAGE_SMOKE]: "1",
    [ENV.DESKTOP_SMOKE_FILE]: markerPath,
  };
}

function createMarkerPath(): string {
  return join(mkdtempSync(join(tmpdir(), "transport-matters-smoke-")), "ready.json");
}

function defaultPackageDir(): string {
  return fileURLToPath(new URL("./package-smoke", import.meta.url));
}

function findDarwinExecutable(packageDir: string): string {
  const executable = findFiles(packageDir).find((candidate) =>
    candidate.includes(".app/Contents/MacOS/") &&
    !candidate.includes("/Contents/Frameworks/"),
  );

  if (executable === undefined) {
    throw new Error(`No packaged macOS app executable found in ${packageDir}.`);
  }
  return executable;
}

function findFiles(directory: string): string[] {
  if (!existsSync(directory)) {
    throw new Error(`Package smoke directory does not exist: ${directory}.`);
  }

  const files: string[] = [];
  for (const entry of readdirSync(directory)) {
    const entryPath = join(directory, entry);
    const stat = statSync(entryPath);
    if (stat.isDirectory()) {
      files.push(...findFiles(entryPath));
    } else if (stat.isFile()) {
      files.push(entryPath);
    }
  }
  return files;
}

function readSmokeStatus(markerPath: string): PackageSmokeResult["status"] {
  const marker = JSON.parse(readFileSync(markerPath, "utf8")) as {
    status?: string;
  };
  if (marker.status !== "main-window-created") {
    throw new Error(`Unexpected desktop smoke status in ${markerPath}.`);
  }
  return marker.status;
}

function waitForExit(child: PackagedChildProcess, timeoutMs: number): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      child.kill?.("SIGTERM");
      reject(new Error(`Desktop package smoke timed out after ${timeoutMs}ms.`));
    }, timeoutMs);

    child.once("error", (error: Error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.once("exit", (code: number | null) => {
      clearTimeout(timer);
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(`Desktop package smoke exited with code ${code}.`));
    });
  });
}

async function main(): Promise<void> {
  const result = await runPackagedAppSmoke();
  console.log(JSON.stringify(result));
}

if (process.argv[1] !== undefined) {
  const entrypointUrl = pathToFileURL(process.argv[1]).href;
  if (import.meta.url === entrypointUrl) {
    void main().catch((error: unknown) => {
      console.error(error instanceof Error ? error.message : String(error));
      process.exitCode = 1;
    });
  }
}
