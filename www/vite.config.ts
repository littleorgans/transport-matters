import { execSync } from "node:child_process";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Single source of truth is the git tag (same source hatch-vcs uses for
// the Python wheel). TRANSPORT_MATTERS_VERSION wins when set explicitly (e.g. from
// release.sh or a hermetic build). Otherwise, derive from `git describe`.
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
    proxy: {
      "/api": {
        target: "http://localhost:8788",
        changeOrigin: true,
      },
    },
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
