import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

const DESKTOP_SRC = new URL("./", import.meta.url);
const ROUTE_TREE_PATTERNS = [
  /RouteLayout/,
  /BrowserAppShell/,
  /createBrowserRouter/,
  /react-router/,
  /from "react"/,
  /from 'react'/,
];

describe("desktop renderer boundary", () => {
  it("does not introduce a duplicate renderer route tree under desktop", () => {
    const offenders = sourceFilesUnder(DESKTOP_SRC.pathname).filter((file) => {
      if (file.endsWith(".test.ts")) {
        return false;
      }
      const content = readFileSync(file, "utf8");
      return ROUTE_TREE_PATTERNS.some((pattern) => pattern.test(content));
    });

    expect(offenders.map((file) => relative(DESKTOP_SRC.pathname, file))).toEqual(
      [],
    );
  });
});

function sourceFilesUnder(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    const stat = statSync(path);
    if (stat.isDirectory()) {
      return sourceFilesUnder(path);
    }
    return path.endsWith(".ts") ? [path] : [];
  });
}
