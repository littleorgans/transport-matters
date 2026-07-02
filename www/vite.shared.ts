import { execSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { type PluginOption, searchForWorkspaceRoot, type UserConfig } from "vite";

/**
 * Shared Vite build shape for the two product bundles (P6: two bundles,
 * separate serving). Each product config passes its own plugins, bundle
 * directory, and base; the dev-only shell reuses resolveVersion() alone.
 */

const workspaceRoot = searchForWorkspaceRoot(path.dirname(fileURLToPath(import.meta.url)));

// Single source of truth is the git tag (same source hatch-vcs uses for
// the Python wheel). TRANSPORT_MATTERS_VERSION wins when set explicitly (e.g. from
// scripts/release.sh or a hermetic build). Otherwise, derive from `git describe`.
// Final fallback is "dev" so the dev server works outside a git checkout.
export function resolveVersion(): string {
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

export interface ProductViteConfigOptions {
  /** Directory under api/src/transport_matters/ the bundle builds into. */
  bundleDir: "www" | "canvas";
  /** Public base path the bundle is served from. Defaults to "/". */
  base?: string;
  plugins: PluginOption[];
}

/**
 * Production bundle config for one product. outDir is anchored to the
 * workspace root so the build lands inside the Python package regardless
 * of the invoking directory; hatch embeds it via the artifacts glob.
 */
export function productViteConfig(options: ProductViteConfigOptions): UserConfig {
  return {
    base: options.base ?? "/",
    plugins: options.plugins,
    define: {
      __TRANSPORT_MATTERS_VERSION__: JSON.stringify(resolveVersion()),
    },
    build: {
      outDir: path.resolve(workspaceRoot, "api/src/transport_matters", options.bundleDir),
      emptyOutDir: true,
    },
  };
}
