import { readFileSync } from "node:fs";
import { createContext, Script } from "node:vm";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ts from "typescript";

const exposeInMainWorld = vi.fn();
const getPathForFile = vi.fn(() => "/tmp/shot.png");

describe("preload bridge", () => {
  beforeEach(() => {
    exposeInMainWorld.mockClear();
  });

  it("exposes appName, platform, and getPathForFile on transportMattersDesktop", async () => {
    executePreload();
    expect(exposeInMainWorld).toHaveBeenCalledTimes(1);
    const [key, api] = exposeInMainWorld.mock.calls[0] as [string, Record<string, unknown>];
    expect(key).toBe("transportMattersDesktop");
    expect(api.appName).toBe("Transport Matters");
    expect(api.platform).toBe("darwin");
    const file = {} as File;
    expect((api.getPathForFile as (f: File) => string)(file)).toBe("/tmp/shot.png");
    expect(getPathForFile).toHaveBeenCalledWith(file);
  });
});

function executePreload(): void {
  const source = readFileSync(new URL("./preload.cts", import.meta.url), "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: {
      esModuleInterop: false,
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      verbatimModuleSyntax: false,
    },
    fileName: "preload.cts",
  });
  const module = { exports: {} };
  const require = (name: string) => {
    if (name !== "electron") throw new Error(`Unexpected preload require: ${name}`);
    return {
      contextBridge: { exposeInMainWorld },
      webUtils: { getPathForFile },
    };
  };
  const context = createContext({
    module,
    exports: module.exports,
    process: { platform: "darwin" },
    require,
  });
  new Script(outputText, { filename: "preload.cjs" }).runInContext(context);
}
