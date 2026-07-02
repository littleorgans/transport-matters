import path from "node:path";
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { searchForWorkspaceRoot } from "vite";
import { defineConfig } from "vitest/config";
import { resolveVersion } from "../../vite.shared";

export const DEV_API_BASE_URL_ENV = "TRANSPORT_MATTERS_DEV_API_BASE_URL";

const packageRoot = path.dirname(fileURLToPath(import.meta.url));
const workspaceRoot = searchForWorkspaceRoot(packageRoot);
const shellSrcRoot = path.resolve(packageRoot, "src");

export function resolveDevApiProxyTarget(env: NodeJS.ProcessEnv = process.env): string | undefined {
  const rawTarget = env[DEV_API_BASE_URL_ENV]?.trim();
  if (rawTarget === undefined || rawTarget.length === 0) {
    return undefined;
  }
  const target = new URL(rawTarget);
  if (target.protocol !== "http:" && target.protocol !== "https:") {
    throw new Error(`${DEV_API_BASE_URL_ENV} must be an HTTP URL.`);
  }
  return target.origin;
}

export function buildDevServerProxy(env: NodeJS.ProcessEnv = process.env) {
  const target = resolveDevApiProxyTarget(env);
  if (target === undefined) {
    return undefined;
  }
  return {
    "/api": {
      target,
      changeOrigin: true,
      // Forward WebSocket upgrades (terminal pane streams over /api/v1/terminal).
      ws: true,
    },
  };
}

// The dev-only composer. No production outDir: `vite build` (the Playwright
// preview/perf path) emits to the local dist/, never into the Python package.
// The inspector and canvas packages own the two production bundles.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: {
    __TRANSPORT_MATTERS_VERSION__: JSON.stringify(resolveVersion()),
  },
  resolve: {
    // Pin the product entries to their src/ lazy entries so the dev shell
    // keeps composing source even if a product's exports map ever repoints
    // at built output. Exact-match regexes: subpath imports (for example
    // @tm/canvas/storageKeys) still resolve through the exports maps.
    alias: [
      {
        find: /^@tm\/inspector$/,
        replacement: path.resolve(packageRoot, "../inspector/src/index.ts"),
      },
      {
        find: /^@tm\/canvas$/,
        replacement: path.resolve(packageRoot, "../canvas/src/index.ts"),
      },
    ],
  },
  server: {
    fs: {
      allow: [workspaceRoot],
    },
    proxy: buildDevServerProxy(),
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: [path.resolve(shellSrcRoot, "test-setup.ts")],
    include: [
      "src/**/*.test.{ts,tsx}",
      "../host/src/**/*.test.{ts,tsx}",
      "../core/src/**/*.test.{ts,tsx}",
      "../inspector/src/**/*.test.{ts,tsx}",
      "../canvas/src/**/*.test.{ts,tsx}",
    ],
  },
});
