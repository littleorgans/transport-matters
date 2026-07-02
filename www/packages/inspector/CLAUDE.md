# @tm/inspector

The Tailwind **web** product: wire-time, reactive. Arm a breakpoint, pause
the live request, edit in flight, release. Served at `/`.

## Boundaries

- Depends on `@tm/core` only (plus npm UI deps). `@tm/host` chrome is
  mounted by the composing entry point, not imported here.
- **Never imports `@tm/canvas`.** Enforced two ways in the shell's test
  suite: the import-graph boundary test (zero inspector to canvas edges,
  either direction) and the dep-lint test (neither product's package.json
  may list the other).
- Public surface is the `exports` map: `.` (the `App` entry plus
  `INSPECTOR_STORAGE_KEYS`) and `./inspector.css`. Everything else is
  internal; deep imports fail the boundary test.

## Owned concerns

- Exchange list and detail, breakpoint stack, editor, overrides/export/
  colorize/charAccounting, `uiStore`, `overlaysStore`, `useRouteHotkeys`.
- `api.ts`: the override and breakpoint endpoints, built on core's
  `requestApiJson`/`requestApiVoid`.
- `inspector.css`: the Tailwind `@theme`, including the accent
  (`--color-accent: #e8e4dc`, `--accent-rgb`). The inspector has **no
  theme system**; its accent pins to the stylesheet (theme clean break,
  locked decision). Some token values are deliberately duplicated in
  `@tm/canvas` — separate tokens per product is a locked decision, do not
  re-unify them.
- Fullscreen Escape is a plain window listener (`hooks/useFullscreen.ts`);
  the inspector renders outside any keybinding engine. The engine-wired
  variant is canvas-only.

## Storage

`stores/persistence.ts` owns this product's localStorage keys. Both
products share one origin; the shell asserts the two registries never
collide, so add new keys there, never inline.
