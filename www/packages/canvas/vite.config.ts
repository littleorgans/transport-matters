import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { productViteConfig } from "../../vite.shared";

// The Ark/BEM desktop product: builds into the Python package's canvas/
// directory, served by the API at /canvas (the desktop shell loads it too).
// base makes every asset URL absolute under /canvas/, so the /canvas-lab
// page (served by the API from this same bundle) resolves assets correctly.
export default defineConfig(
  productViteConfig({ bundleDir: "canvas", base: "/canvas", plugins: [react()] }),
);
