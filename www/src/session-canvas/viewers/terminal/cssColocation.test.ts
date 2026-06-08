import { readdirSync, readFileSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

// Mirrors viewers/resource/cssColocation.test.ts for the terminal viewer: a
// bare `import "./x.css"` is a side effect with no typed binding, so if nothing
// in the bundle graph imports it the bundler drops the stylesheet and the pane
// ships unstyled while every gate stays green (the PR#58 M1 lesson). Requiring
// each stylesheet to be imported by a co-located module makes that impossible.
const terminalDir = dirname(fileURLToPath(import.meta.url));
const indexCss = join(terminalDir, "..", "..", "..", "index.css");

function cssFilesUnder(dir: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) found.push(...cssFilesUnder(full));
    else if (entry.name.endsWith(".css")) found.push(full);
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

describe("terminal-viewer CSS is co-located, never global", () => {
  const cssFiles = cssFilesUnder(terminalDir);

  it("ships at least one co-located stylesheet", () => {
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

  it("adds no terminal styles to the global index.css", () => {
    const global = readFileSync(indexCss, "utf8");
    expect(global).not.toContain("terminal-pane");
    expect(global).not.toContain("xterm");
  });
});
