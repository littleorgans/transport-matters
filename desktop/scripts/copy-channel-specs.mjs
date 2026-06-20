import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const source = resolve(
  scriptDir,
  "../../api/src/transport_matters/channel-specs.json",
);
const target = resolve(scriptDir, "../dist/channel-specs.json");

mkdirSync(dirname(target), { recursive: true });
copyFileSync(source, target);
