# www

Modern Vite 8 + React 19 + TypeScript starter with production infrastructure wired in.

## Stack

- **Build**: Vite 8 (Rolldown)
- **Lint + Format**: Biome v2 (single tool, no ESLint/Prettier)
- **Styles**: Tailwind CSS v4 (CSS-based config)
- **Unit Tests**: Vitest 4.1 + React Testing Library
- **E2E Tests**: Playwright (3 browsers)
- **CI**: GitHub Actions (Node 20/22 matrix)
- **Releases**: Changesets
- **Git Hooks**: Lefthook (lint staged files, conventional commits)
- **TypeScript**: Strict mode with additional safety flags

## Getting Started

```bash
pnpm install
pnpm dev
```

## Scripts

| Command | Description |
|---|---|
| `pnpm dev` | Start dev server |
| `pnpm build` | Type check + production build |
| `pnpm test` | Run unit tests |
| `pnpm test:watch` | Run unit tests in watch mode |
| `pnpm test:e2e` | Run Playwright E2E tests |
| `pnpm lint` | Lint and format check |
| `pnpm lint:fix` | Auto-fix lint and format issues |
| `pnpm typecheck` | TypeScript type checking |
| `pnpm release <ver>` | Cut a tagged release (see `../scripts/release.sh`) |

## Project Structure

```
src/
  features/       # Feature modules (colocate components, hooks, tests)
  shared/         # Cross-feature code
    components/   # Reusable UI components
    hooks/        # Shared hooks
    lib/          # Third-party wrappers, utilities
  app.tsx         # Root component
  index.css       # Tailwind entry
  main.tsx        # React entry
tests/
  e2e/            # Playwright E2E tests
```

Features own their components, hooks, and tests. Shared code lives in `shared/`. Import rule: features import from `shared/` or within themselves, never from other features.

## Adding Common Libraries

```bash
# Routing
pnpm add @tanstack/react-router

# Data fetching
pnpm add @tanstack/react-query

# State management
pnpm add zustand

# Component library
npx shadcn@latest init

# Form validation
pnpm add react-hook-form zod
```
