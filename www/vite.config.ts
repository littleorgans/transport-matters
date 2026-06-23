import { execSync } from "node:child_process";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export const DEV_API_BASE_URL_ENV = "TRANSPORT_MATTERS_DEV_API_BASE_URL";

// Single source of truth is the git tag (same source hatch-vcs uses for
// the Python wheel). TRANSPORT_MATTERS_VERSION wins when set explicitly (e.g. from
// scripts/release.sh or a hermetic build). Otherwise, derive from `git describe`.
// Final fallback is "dev" so the dev server works outside a git checkout.
function resolveVersion(): string {
  const envVersion = process.env.TRANSPORT_MATTERS_VERSION;
  if (envVersion && envVersion.length > 0) return envVersion.replace(/^v/, "");
  try {
    const described = execSync("git describe --tags --always --dirty", {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
    return described.replace(/^v/, "") || "dev";
  } catch {
    return "dev";
  }
}

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

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: {
    __TRANSPORT_MATTERS_VERSION__: JSON.stringify(resolveVersion()),
  },
  resolve: {
    alias: {
      "@": "/src",
    },
  },
  server: {
    proxy: buildDevServerProxy(),
  },
  build: {
    outDir: "../api/src/transport_matters/www",
    emptyOutDir: true,
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
