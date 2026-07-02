/**
 * Dependency lint: the two products are peers and must never depend on
 * each other, in any dependency field. The import-graph boundary test
 * catches source-level edges; this catches the manifest-level edge that
 * would let one product resolve the other at all.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const PACKAGES_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");

const DEPENDENCY_FIELDS = [
  "dependencies",
  "devDependencies",
  "peerDependencies",
  "optionalDependencies",
] as const;

function declaredDependencies(packageName: "inspector" | "canvas"): string[] {
  const manifest = JSON.parse(
    readFileSync(path.join(PACKAGES_ROOT, packageName, "package.json"), "utf8"),
  ) as Record<(typeof DEPENDENCY_FIELDS)[number], Record<string, string> | undefined>;
  return DEPENDENCY_FIELDS.flatMap((field) => Object.keys(manifest[field] ?? {}));
}

describe("product dependency lint", () => {
  it("inspector never depends on @tm/canvas", () => {
    expect(declaredDependencies("inspector")).not.toContain("@tm/canvas");
  });

  it("canvas never depends on @tm/inspector", () => {
    expect(declaredDependencies("canvas")).not.toContain("@tm/inspector");
  });
});
