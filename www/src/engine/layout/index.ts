// Auto-discover every strategy file so each registers itself on import. Adding a strategy file to
// ./strategies/ is therefore zero other edits (spec §6 extensibility proof). Vite and Vitest both
// transform import.meta.glob; { eager: true } runs each module's top-level registerLayout call.
import.meta.glob("./strategies/*.ts", { eager: true });

export * from "./configs";
export * from "./fit";
export * from "./params";
export * from "./registry";
export * from "./types";
