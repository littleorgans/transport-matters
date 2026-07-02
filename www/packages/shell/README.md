# @tm/shell

Dev-only composer for the Transport Matters browser products. One origin
serves both products for development; the shell ships in no production
bundle. Production bundles are owned by the products themselves:
`@tm/inspector` builds into `api/src/transport_matters/www/` (served at
`/`) and `@tm/canvas` into `api/src/transport_matters/canvas/` (served at
`/canvas`, plus the `/canvas-lab` page). Root `just build` ships both.

## Commands

Run from the repository root:

```bash
pnpm install
pnpm --filter @tm/shell dev
pnpm --filter @tm/shell test
```

`pnpm --filter @tm/shell build` emits to the package-local `dist/` for the
Playwright preview/perf path only; nothing lands inside the Python package.
