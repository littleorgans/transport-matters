import {
  chmodSync,
  copyFileSync,
  cpSync,
  existsSync,
  mkdirSync,
  readdirSync,
  renameSync,
  rmSync,
  statSync,
} from "node:fs";
import { execFileSync } from "node:child_process";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const projectDir = resolve(scriptDir, "..");
const electronDist = resolve(projectDir, "node_modules/electron/dist");
const packageOut = resolve(projectDir, "dist/package-smoke");
const appName = "Transport Matters";

rmSync(packageOut, { force: true, recursive: true });
mkdirSync(packageOut, { recursive: true });

if (process.platform === "darwin") {
  buildDarwinPackage();
} else {
  buildPortablePackage();
}

function buildDarwinPackage() {
  const sourceApp = join(electronDist, "Electron.app");
  const targetRoot = join(packageOut, `${appName}-darwin-${process.arch}`);
  const targetApp = join(targetRoot, `${appName}.app`);
  mkdirSync(targetRoot, { recursive: true });
  execFileSync("/bin/cp", ["-R", sourceApp, targetApp]);
  rmSync(join(targetApp, "Contents/Resources/default_app.asar"), {
    force: true,
  });
  copyAppSources(join(targetApp, "Contents/Resources/app"));
}

function buildPortablePackage() {
  const targetRoot = join(packageOut, `${appName}-${process.platform}-${process.arch}`);
  cpSync(electronDist, targetRoot, { recursive: true });
  const executable = process.platform === "win32" ? "electron.exe" : "electron";
  const targetExecutable =
    process.platform === "win32" ? `${appName}.exe` : appName;
  const executablePath = join(targetRoot, executable);
  if (existsSync(executablePath)) {
    renameSync(executablePath, join(targetRoot, targetExecutable));
    if (process.platform !== "win32") {
      chmodSync(join(targetRoot, targetExecutable), 0o755);
    }
  }
  copyAppSources(join(targetRoot, "resources/app"));
}

function copyAppSources(targetDir) {
  mkdirSync(targetDir, { recursive: true });
  cpSync(resolve(projectDir, "assets"), join(targetDir, "assets"), {
    recursive: true,
  });
  copyDirectory(resolve(projectDir, "dist"), join(targetDir, "dist"));
  copyFileSync(resolve(projectDir, "package.json"), join(targetDir, "package.json"));
}

function copyDirectory(source, target) {
  mkdirSync(target, { recursive: true });
  for (const entry of readdirSync(source)) {
    if (entry.startsWith("package-smoke")) {
      continue;
    }
    const sourcePath = join(source, entry);
    const targetPath = join(target, entry);
    const stat = statSync(sourcePath);
    if (stat.isDirectory()) {
      copyDirectory(sourcePath, targetPath);
    } else if (stat.isFile()) {
      copyFileSync(sourcePath, targetPath);
    }
  }
}
