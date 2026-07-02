# @tm/shell

Dev shell for the Transport Matters browser app during the www separation.
Phase 3 keeps one Vite bundle and moves the retired single app under the
repo-root pnpm workspace.

## Commands

Run from the repository root:

```bash
pnpm install
pnpm --filter @tm/shell dev
pnpm --filter @tm/shell build
pnpm --filter @tm/shell test
```

The bundle still builds to `api/src/transport_matters/www/` and is served at `/`.
