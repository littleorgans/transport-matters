/**
 * @tm/inspector — the Tailwind web product: exchange list and detail,
 * breakpoint arm/pause/edit/release. The shell lazy-loads `App`;
 * `INSPECTOR_STORAGE_KEYS` is public so the shell can assert the two
 * products' localStorage registries never collide.
 */
export { App } from "./app";
export { INSPECTOR_STORAGE_KEYS } from "./stores/persistence";
