# @tm/canvas

The Ark + vanilla BEM CSS **premium desktop** product: config-time,
proactive overlay editing ahead of the request. Served at `/canvas`
(desktop loads it too). Zero Tailwind. **No breakpoint.**

## Boundaries

- Depends on `@tm/core` only (plus npm UI deps: Ark, dnd-kit,
  framer-motion, xterm, tinykeys). `@tm/host` chrome is mounted by the
  composing entry point, not imported here.
- **Never imports `@tm/inspector`.** Enforced two ways in the shell's
  test suite: the import-graph boundary test (zero edges either
  direction) and the dep-lint test (neither product's package.json may
  list the other). The exchange viewer is the Ark fork
  (`ArkExchangeViewer`), not the inspector's `ExchangeDetail` — locked
  decision, do not reach back.
- Public surface is the `exports` map: `.` (the two routes, the theme
  store and `clearThemeTokens` for the shell's composition test,
  `CANVAS_STORAGE_KEYS`), `./index.css`, and
  `./ambient/createAmbientBackground` (exposed so the shell's
  composition test can mock the WebGL boundary). Everything else is
  internal; deep imports fail the boundary test.

## Owned concerns

- `session-canvas/**` (panes, launcher, viewers, dnd, capture stores),
  the pane layout `engine/`, `ambient/` scenes.
- **The theme system** (`theme/`, `themeStore`, `useThemeTokens`) is
  canvas-only by locked decision. Themes override `--color-accent`,
  `--accent-rgb`, and the `--pane-*` knobs inline on `:root`;
  `styles/tokens.css` carries the unthemed defaults. Token values shared
  with the inspector are deliberate copies — do not re-unify.
- The keybinding engine (`keybindings/engine.ts`), gestures, and the
  `COMMANDS` registry, including `ui.exitFullscreen`: the canvas Escape
  order (palette, dock, fullscreen) depends on engine registration, and
  `ArkExchangeViewer` registers its fullscreen through
  `session-canvas/hooks/useFullscreen.ts`. `keymapStore` lives here (its
  state is the canvas gesture modifier).
- `session-canvas/lab/**` is fenced by the lab boundary test: non-lab
  code never imports lab modules.

## Storage

`session-canvas/persistence/storageKeys.ts` owns this product's
localStorage keys. Both products share one origin; the shell asserts the
two registries never collide, so add new keys there, never inline.
