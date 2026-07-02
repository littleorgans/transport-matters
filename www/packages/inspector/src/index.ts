/**
 * @tm/inspector — the Tailwind web product: exchange list and detail,
 * breakpoint arm/pause/edit/release. The shell lazy-loads `App`. The
 * localStorage registry lives on the css-free `./storageKeys` subpath so
 * Node-side test transforms (Playwright) never pull the component graph.
 */
export { App } from "./app";
