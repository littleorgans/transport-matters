import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

const BROWSER_IDENTITY_SURFACES = [
  "package.json",
  "index.html",
  "vite.config.ts",
  "src",
  "tests/visual/fixtures",
] as const;

const OLD_SLUG = ["mani", "cure"].join("");
const OLD_LABEL = ["Mani", "cure"].join("");
const OLD_VERSION_ENV = ["MANI", "CURE_VERSION"].join("");
const OLD_VERSION_GLOBAL = ["__", OLD_VERSION_ENV, "__"].join("");

const OLD_IDENTITIES = [
  OLD_SLUG,
  OLD_LABEL,
  OLD_VERSION_ENV,
  OLD_VERSION_GLOBAL,
  [OLD_SLUG, "ui"].join("-"),
  [OLD_SLUG, "overlays"].join("-"),
  [OLD_SLUG, "panel", "dismissed"].join("."),
] as const;

function collectTextFiles(path: string): string[] {
  if (statSync(path).isFile()) return [path];

  return readdirSync(path, { withFileTypes: true }).flatMap((entry) => {
    const entryPath = join(path, entry.name);
    if (entry.isDirectory()) return collectTextFiles(entryPath);
    if (!entry.isFile()) return [];
    if (entry.name.endsWith(".png")) return [];
    return [entryPath];
  });
}

describe("browser product identity", () => {
  it("keeps active browser surfaces on the Transport Matters identity", () => {
    const offenders: string[] = [];
    for (const surface of BROWSER_IDENTITY_SURFACES) {
      for (const filePath of collectTextFiles(join(ROOT, surface))) {
        const content = readFileSync(filePath, "utf8");
        for (const oldIdentity of OLD_IDENTITIES) {
          if (content.includes(oldIdentity)) {
            offenders.push(`${relative(ROOT, filePath)} contains ${oldIdentity}`);
          }
        }
      }
    }

    expect(offenders).toEqual([]);
  });
});
