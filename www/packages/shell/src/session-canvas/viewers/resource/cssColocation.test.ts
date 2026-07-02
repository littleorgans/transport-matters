import { readdirSync, readFileSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

// Resolve the resource-viewers directory from this test's own location so the
// guard tracks the real tree rather than a hard-coded list.
const resourceDir = dirname(fileURLToPath(import.meta.url));

function cssFilesUnder(dir: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      found.push(...cssFilesUnder(full));
    } else if (entry.name.endsWith(".css")) {
      found.push(full);
    }
  }
  return found;
}

function coLocatedModules(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true })
    .filter(
      (entry) => entry.isFile() && /\.tsx?$/.test(entry.name) && !entry.name.includes(".test."),
    )
    .map((entry) => entry.name);
}

const cssFiles = cssFilesUnder(resourceDir);

describe("resource-viewer CSS is co-located with the component that renders it", () => {
  // A bare `import "./x.css"` is a side effect with no typed binding. If nothing
  // in the bundle graph imports it, the bundler drops the stylesheet and the
  // viewer ships unstyled while every gate stays green (PR#58 M1:
  // exchange-viewer.css was imported nowhere). Requiring each stylesheet to be
  // imported by a module sitting next to it makes "shipped unstyled"
  // structurally impossible: you cannot render the component without pulling its
  // styles into the graph.
  it("finds the resource stylesheets", () => {
    expect(cssFiles.length).toBeGreaterThan(0);
  });

  it.each(
    cssFiles.map((cssPath) => [basename(cssPath), cssPath] as const),
  )("%s is imported by a co-located module", (_name, cssPath) => {
    const dir = dirname(cssPath);
    const importSpecifier = `./${basename(cssPath)}`;
    const importers = coLocatedModules(dir).filter((moduleName) =>
      readFileSync(join(dir, moduleName), "utf8").includes(importSpecifier),
    );
    expect(importers).not.toEqual([]);
  });
});
