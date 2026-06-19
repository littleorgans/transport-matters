# NOW

What we are working on and what we must not lose sight of. This doc holds **WIP, current
focus, and a parking lot of live ideas** — not a history of shipped work. Merged work leaves
this file. When scope drifts, this is the anchor.

## ★ North Star — read first; every architectural and design decision goes through this lens

The human operates agents by **voice → a director agent** that holds full context of every
workspace/canvas/pane and **launches, manages, and prompts** agents via **MCP or CLI**. The
discipline this imposes: **API-first, the UI is one client of two.** The director and the
human ⌘K palette are twin clients of one control plane (verbs: **observe / launch / manage /
prompt**); anything the UI can do, the director must do programmatically. No UI-only logic.

Full vision + the decision lens: `~/.mdx/projects/transport-matters-north-star.md`. Apply it
to everything below.

## ★ Current focus — finish the ⌘K launcher

The launcher is shipped end to end except two scope stubs: zero-chrome ⌘K command center,
domains-first root, keybinding engine, action/nav/interaction model, and the
Agents/Canvas/Settings scopes (Ark UI via `Combobox`). The Agents scope is a real spawn
launcher with recommendation-default logic, native-always-present, and
loading/error/empty/populated states. The recommendation-default path is **live end to end**:
TM's `runtime_registry` reads schema-2 `capabilities.json` from `~/.agent-runtimes/runtimes`
(shipped + committed), all templates carry `recommended_model.default` / `by_vendor`, surfaced
through `runtime_template_routes.py get_runtime_templates` → `GET /v1/runtime-templates` → the
`www` Agents launcher (`commandModel templateSpawnHarness` / `recommendedSubtitle`). Verified
by running the registry reader against the live data.

One gap remains before the launcher is whole:

- **Workdir + Sessions launcher scopes.** Both are disabled `buildDeferredRows` placeholders
  today (`commandModel buildScopeRows`). Design them into real scopes. The Sessions *launcher
  scope* is distinct from the live canvas transcript reader (track 2 below).

Refs: `~/.mdx/projects/transport-matters-launcher-ui-spec.md` (complete),
`~/.mdx/projects/tm-ui-component-strategy.md`. `cli`→`harness` rename done; spec complete.

## Next up — committed tracks, not yet started

### 1. User onboarding

First-run welcome flow in the desktop. Nothing built yet (the only artifact is
`FirstRunHint.tsx`, a ⌘K discoverability hint, unrelated).

- Detect the installed CLI (Claude Code / Codex), cache its version and the **first frame
  payload** (first outbound request: baseline system prompt + tool schemas) as the
  **drift-detection baseline**.
- New user (empty `~/.transport-matters`): guided walk through ENV & settings, then edit
  overlays. Returning user: diff the current first frame against the baseline; if it moved,
  "system prompts updated by provider" → route to edit overlays. `--yolo`: auto-capture, skip
  the walk.
- **Coupling:** onboarding's "ENV & settings → edit overlays" is the **same config/overlay
  surface** the desktop manages. Build the overlay model once or it forks.

### 2. Session transcripts — progressive subtraction

Browse + view shipped (chat UI, full `nativePayload`, nothing filtered — complete visibility
is the product). Next, in order:

- **S2 denylist:** append-only JSON-path list (`~/.transport-matters/transcript_denylist.json`),
  default empty, UI-side presentation filter. Reveal everything, then hide what's decided not
  useful.
- **search** across stored transcripts — pending.
- **import** the CLI's recorded stream into the DB — pending (`WORK-REMAINING` §9).
- **F2 open decision:** cap `raw` size on the SSE stream (full inline base64 per frame) vs
  accept it per complete-visibility.
- Not in this track: replay, fork, share, eval. Deferred, not dropped.

### 3. Ephemeral-home loose ends

Runtime-home slices are merged. Two follow-ups still open:

- Drop the now test-only `cli/runtime_home.py` re-export of the template types.
- Amend the ephemeral-home spec §6/§10/§11 provenance language to match the shipped Postgres
  persistence (migration `0005`, `template_provenance`).

Fork / share / eval are the destination of the agent-runtimes initiative, not this phase.

## On our mind — don't lose sight

- **Canvas keyboard zoom/pan migration.** `+`/`-`/`=` zoom and `Alt`+Arrow pan
  (`engine/react/useCanvasViewport.ts`) were deferred out of the keybinding registry. Folding
  them in is now a one-entry-per-command change — and the moment to fix the known `Alt`+Arrow
  vs browser Back/Forward collision (a11y). Design:
  `~/.mdx/projects/transport-matters-launcher-design--authoritative.md`.
- **Per-agent resource monitoring.** Captured agents occasionally spawn CPU/IO-heavy work
  (e.g. a `find` from `$HOME`); surface per-run CPU/mem/IO. Natural fit for the `RunManager`
  seam. Unimplemented.
- **Bounded shared-proxy pool (HQ5 headroom).** Canvas runs share one `mitmdump` (K=1). The
  load harness shows the CPU knee around ~50 concurrent *active* streams. Fallback is K shared
  subprocesses — `SharedProxyManager` generalized 1→K with **K=1 as a byte-for-byte identity
  default** so it ships dark and flips on via `shared_proxy_pool_size`. Not the focus
  (single-user load won't stream 50 panes at once) but execution-ready: ~4 engineer-days /
  ~650 LoC / 3 PRs, change concentrated in `manager.py`. Spec:
  `~/.mdx/projects/tm-tier2-bounded-pool-design.md`.
- **Canvas-layout server store (resume-S6 gate).** Canvas layout is client-side
  (zustand → localStorage) today. A server store only materializes if layout must persist
  **across the boundary of one browser profile** (cross-device / reinstall / share). Until
  that requirement is real, do-nothing. When real: a separate `workspaceId`-keyed aggregate,
  capture ids as soft refs (no FK), deleted session → placeholder pane, server is a sync
  target not the owner.
- **Bypass-permissions visual surfacing (PR #155 review M6/M7).** The "Bypass all permission
  checks" toggle (shipped `fde5665`) is a sticky-global persisted flag with no on-canvas
  indicator: a forgotten On silently skips all permission prompts on every future run, and a
  pane launched in bypass keeps running in bypass with no badge after the toggle flips off.
  Revisit when we add **per-pane icons / header affordances** (pane header already has
  `F`/`E`/`-`/`CLOSE` + a harness mascot on Claude panes) — fold in a persistent canvas banner
  while bypass is On and a per-pane bypass badge alongside the pane icon. Findings:
  `~/.mdx/projects/yolo-toggle-review.md`.
- **No-DB startup + store picker (researched, not committed).** A DB stays
  required; embedded is a zero-config no-brainer for non-technical users, not a
  docker/hosted replacement. TM deliberately refuses to launch with no Postgres via
  **two guards** — `launch_runtime.py preflight_session_store_or_exit` (front of
  every CLI launch; `exit(2)` before proxy/run-dir/agent) and
  `run_manager.py RunManager._ensure_session_store_available` (blocks `POST /v1/runs`
  canvas spawn). Everything else already degrades: tier-1 disk capture
  (`DiskStorageBackend.persist_exchange`), `main.lifespan`, `SessionWriter`, the
  LISTEN/NOTIFY listener. So a degraded "capture-to-disk, watch the live run" mode +
  a store picker needs only: relax the two guards, add a `db_status` signal to
  `/api/meta` (www learns DB status nowhere today), and a `RootShell` picker
  (local pgembed / docker / hosted DSN) ahead of `selectRootRoute`'s canvas fork.
  Blast surface is small and confirmed: API 8 HARD (the `session_routes` cluster +
  `POST /v1/runs`) / 29 SOFT (per-run exchange reads are disk-backed, survive); the
  frontend gate is **exactly 3 mounted consumers, all under `/canvas`**
  (`SessionPickerPane`, `TranscriptChatPane`, resource `ResourcePane` via
  `session-canvas/api/*`) — 2-pane MoE confirmed, legacy `/` route needs no gate.
  Couples with Next-up #1 (User onboarding): same ENV/settings → edit-overlays
  surface. Findings: `~/.mdx/projects/transport-matters-nodb-mode-findings.md`;
  embedded-PG path: `~/.mdx/projects/transport-matters-litepg-landscape.md`.
