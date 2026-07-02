import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { productViteConfig } from "../../vite.shared";

// The Tailwind web product: builds into the Python package's www/ directory,
// served by the API at "/".
export default defineConfig(
  productViteConfig({ bundleDir: "www", plugins: [react(), tailwindcss()] }),
);
