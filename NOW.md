# NOW

What we are working on next. This doc grounds focus. When scope drifts, this is the anchor.

## ★ North Star — read first; every architectural and design decision goes through this lens

The human operates agents by **voice → a director agent** that holds full context of every
workspace/canvas/pane and **launches, manages, and prompts** agents via **MCP or CLI**. The
discipline this imposes: **API-first, the UI is one client of two.** The director and the
human ⌘K palette are twin clients of one control plane (verbs: **observe / launch / manage /
prompt**); anything the UI can do, the director must do programmatically. No UI-only logic.

Full vision + the decision lens: `~/.mdx/projects/transport-matters-north-star.md`. Apply it
to everything below.

## Ephemeral `.agent-runtimes` homes — Slices 1-4 merged (backend complete through the registry seam); the desktop template-picker UI is the remaining piece (feeds track #2)

Launch Claude/Codex from a **pristine `.agent-runtimes/<name>` template** into a TM-owned **per-run ephemeral home**: template never mutated, auth injected from native `~/.claude`/`~/.codex`, durable history in Postgres (home is disposable). Spec (dual-clean): `~/.mdx/projects/agent-runtimes-ephemeral-home-spec.md`.

- **Slice 1 — PR #118** (`feat/runtime-home-slice1`, gate green, **owner-roadtested ✓**): unify the launch path onto one overlay+seed helper, add `RuntimeHomePlan`, route `run_codex` through it, **source auth from native as fallback** (fixed the desktop/canvas-pane Codex re-auth bug — verified: `tm desktop` → spawn Codex against a pristine template → `auth.json` carried over, auth works), bind descriptor/tailer/rollout to the runtime home, make `projects/`/`sessions/` local. **Merged** (`044556b`, 2026-06-15, dual-clean MoE review + owner roadtest). Follow-up fix seeds captured Codex sessions into the runtime home — they had been landing in the template's `sessions/`, so `codex resume` from a desktop pane failed with "No saved session found".
- **Slice 2 — PR #119** (`feat/runtime-home-slice2`, dual-clean MoE review): split `content_source` / `auth_source` / `hook_trust_source` in the overlay+seeder, symlink rotating credentials from native auth (Claude `.credentials.json`, Codex `auth.json`) instead of copying content, pin content config reads to the template, repoint Codex hook trust at the runtime home. macOS Claude auth owner-verified; Linux `.credentials.json` symlink covered by automated test. **Merged** (`da57a2a`, 2026-06-15).
- **Slice 3 — PR #121** (`feat/runtime-home-slice3`, "enforce template runtime home materialization", dual-clean MoE review): TEMPLATE-mode materialization with the config secret scan, native credential symlinks, missing-template-root hard-fail, and the writer audit in `PROJECT.md`. Per owner decision the allow-list **no longer fails on unknown entries** — unknowns default to symlink-include, `runtime.toml`/`.git` on the explicit ignore set, local-writable paths kept local. Allow-list is on probation; the moment it costs a debugging session it gets nuked. `rmtree` teardown stays deferred (this PR is its evidence gate). **Merged** (`9065950`, 2026-06-15). MoE earned its keep: the Codex reviewer caught a secret-scan Blocker (`OPENAI_API_KEY` slipped an exact-match scan) the Claude pass missed.
- **Slice 4 — PR #128** (`feat/runtime-home-slice4`, `5b1678d`, MoE dual-clean): registry seam (`runtime_registry.py` resolver + stdlib-only `runtime_templates.py` value objects) + `runtime_template` plumbing threaded request-edge → `SpawnRun` → `CapturedRunRequest` → `plan_runtime_home` (TEMPLATE mode), routed through the planning path so it wins the carrier merge (the gotcha held). Provenance persisted as a declared `template_provenance` field on launch facts AND — **owner-ratified scope expansion beyond the spec's launch-facts-only scope** — into Postgres session rows via migration `0005`, `COALESCE` first-writer-wins so a tailer poll cannot clobber it. **Merged** (`5b1678d`, 2026-06-16). Three review findings fixed and verified (dead `cli/runtime_registry.py` compat shim, 3× provenance-transform DRY folded into `RuntimeHomePlan.template_provenance_field`, a non-hermetic Codex CA test CI caught after a false local green). **Follow-ups (deferred):** (a) drop the now-test-only `cli/runtime_home.py` re-export of the template types; (b) amend the spec's §6/§10/§11 provenance language to match the shipped Postgres persistence; (c) the **desktop template-picker UI** that sends a template name on `CreateRunRequest` is the remaining ephemeral-home piece, feeds track #2.
- Feeds track #2 (tm owns the launch config) and the agent-runtimes initiative. Coordinated with the B6 curated `/v1` API workstream (shared launch-field carrier owned here; B6 continuation depends on Slice 1's descriptor binding). Runtimes now live at the permanent home `~/.agent-runtimes/runtimes`.

Three tracks, no committed order yet. Fork/share/eval are the destination, not this phase.

## B6 curated `/v1` API — ✓ COMPLETE

The product API seam #2 and #3 sit on, and the gate the ephemeral-home Slice 4 waits on. **Design ratified** (warroom-reviewed, 0 blockers): [`NOTES/captured-canvas/b6-api-spec.md`](NOTES/captured-canvas/b6-api-spec.md). One converged `/v1` namespace replacing `/api/*` in place; curated product nouns (workspace, session, transcript, run, resource) behind the RunManager/session boundary, no internals on the wire.

- Build order: **§2 session schema** ✓ #122 → **runs family** ✓ #123 → **sessions family** ✓ #124 (+ the track #3 transcript-chat UI) → **continuation** ✓ #127 (`b60442b`). **B6 COMPLETE.** Continuation landing fully unblocks ephemeral-home Slice 4.
- **Canvas-layout is NOT a B6 noun** (spec D2): it is desktop view-state owned client-side by zustand (`canvasStore`/`canvasLabStore` → localStorage). A server store only materializes if layout must persist **across the boundary of one browser profile** (cross-device / reinstall / share) — the resume-S6 gate. Then it is a separate aggregate: `workspaceId`-keyed, capture ids as soft refs (no FK), deleted session → placeholder pane, server store is a sync target not the owner. Until that requirement is real, the slice is do-nothing.
- **D4 continuation constraint** (from #122 review): classification is set-once — `purpose`/`visibility` preserved via `COALESCE`, so the continuation row's FIRST write must carry `purpose=continuation` (mint-before-tail), else a tailer poll pins it to `user` and orphans it from `/v1/sessions?purpose=continuation`. Same for any `internal_*` session. Guard test `test_session_upsert_preserves_existing_classification` in place.
- Run-lifecycle vocabulary (settled): `interrupt` (halt the turn, run lives — ESC over the WS) / `detach` (viewer leaves) / `terminate` (run dies, the REST teardown). Retires the overloaded `stop`.
- Full remaining-work backlog: [`NOTES/WORK-REMAINING.md`](NOTES/WORK-REMAINING.md).

## 1. User onboarding

First-run welcome flow in the desktop.

- Detect the installed CLI (Claude Code / Codex), cache its version and the **first frame payload** (the first outbound request: baseline system prompt + tool schemas).
- That cached first frame is the **drift-detection baseline**. Onboarding pulls double duty: it seeds the baseline that later diffs surface as provider drift.
- New user (empty `~/.transport-matters`): guided walk through ENV & settings, then edit overlays.
- Returning user: diff the current first frame against the cached baseline. If it moved, "system prompts updated by provider", route to edit overlays to reconcile.
- `--yolo`: auto-capture the first frame, skip the guided walk.

## 2. Desktop cleanup — run-ahead ✓ DONE (#140 + #141, owner-roadtested ✓); UI now the focus

Make the desktop opinionated. tm owns the launch config; it is not a flag passthrough. Specs: `~/.mdx/projects/transport-matters-desktop-cleanup/` (`spec-backend.md`, `spec-frontend.md`).

**Run-ahead ✓ merged** — Slice A (#140 `3c4148b`) + Slice B (#141 `4c8feec`), both MoE dual-clean:
- Desktop no longer spawns Claude/Codex in the terminal. Electron owns the backend child via a new server seam (`run_desktop_backend_server`/`serve_desktop_backend` → `create_app`, with `preflight_session_store_or_exit` retained so a misconfigured DB hard-blocks rather than 503s); `transport-matters desktop` is a thin opener; the captured pane path (`prepare_captured_run` → `RunManager` → PTY → xterm) is the only desktop launch.
- Removed the `desktop` passthrough + provider-flag surface: `desktop` now rejects `--agent`/provider flags/`-- args`; the dead validator cluster + `AgentName` import deleted; `_spawn_request` no longer sources `default_client_passthrough` (field/env/param kept for standalone + shared proxy). Standalone `transport-matters claude`/`codex` untouched.
- **Owner live-smoke ✓** (2026-06-18, the launch-wiring gate): clean-shell `tm desktop` → no agent attached to the terminal → Claude + Codex panes spawn through the captured pane path → `--agent`/provider flags rejected → standalone `tm claude -- …` passthrough still works. Run-ahead is real.

**UI effort — design LOCKED (2026-06-18), ready to spec into slices.** Framed by the ★ North Star: the ⌘K palette is **client #1 of the control plane's Launch verb**. Full UI/UX design: `~/.mdx/projects/transport-matters-launcher-ui-spec.md`. Headless layer: Ark UI per `~/.mdx/projects/tm-ui-component-strategy.md`.
- **⌘K command center, scoped by domain** (Agents/Workdir/Canvas/Settings/Sessions); **⌘A** jumps straight to Agents. Zero-chrome canvas. Grammar: ↵ enter/spawn · → configure · ⌫/← back · Esc close. Each domain = a face of the control plane (Agents=Launch, Canvas=Manage/Observe, Settings=manage-agents, Sessions=Observe).
- **Agents scope = the launcher**: agent-first, recommendation-default. Pick an agent → ↵ spawns its recommended target; → expands harness/vendor/model/effort overrides (the eval path). Native always present + spawnable (loading/empty/error all degrade to Native-only).
- **Data deps:** reads `recommended_model.default`/`by_vendor` from `capabilities.json` **v2** (harness/vendor split — schema-2 + fleet regen shipped by agent-runtimes 2026-06-18, uncommitted; topic `tm-launcher-proposal`). TM read-side + the `cli`→`harness` rename are in flight (rename delegated to an orchestrator, blocks the read-side). `GET /v1/runtime-templates` builds with its consumer; `CreateRunRequest` extends with harness/vendor/model/effort (absent → NATIVE).
- **Build order:** RouteSwitcher→Ark `Menu` pilot → Agents scope (⌘A + launcher, the load-bearing slice) → root command-center shell → Canvas/Settings/Workdir/Sessions. (Supersedes the old `spec-frontend.md` template-picker scope, now subsumed.)

## 3. Session transcripts (read surface)

Browse and read past sessions. Non-interactive. Served by the B6 sessions family (curated `Session`/`TranscriptEvent`/`timeline`).

- **browse + view** ✓ shipped: list sessions, open one, render turns as a clean chat UI (#124), with the **full native record surfaced** (#125 reveal-all + #126 cleanup, owner-roadtested ✓).
- **Complete visibility is the product.** The transcript UI beats the CLI terminal because nothing is hidden — every record (hooks, attachments, output styles, reminders, injected file/memory/queued content) renders its full `nativePayload`, not a curated subset. No subtype is filtered. See cm "Transcript reveal-all".
- **S2 — denylist (next):** progressive subtraction via an append-only JSON-path list (`~/.transport-matters/transcript_denylist.json`), default empty, UI-side presentation filter. Reveal everything, then hide what's decided not useful.
- **F2 — open decision:** cap `raw` size on the SSE stream (full inline base64 ships per frame) vs accept it per complete-visibility.
- **search**: query across stored transcripts — pending.
- **import**: persist the CLI's recorded stream into the DB — pending (`WORK-REMAINING` §9).
- Transcript = exactly what the CLI wrote, as persisted. Not the wire. One stream for now.
- Not in this track: replay, fork, share, eval. Deferred, not dropped. This read surface is the floor they build on.

## Couplings to respect

- **#1 and #2 share a config model.** "Options tm manages in the desktop" (#2) and "ENV & settings → edit overlays" (#1) are the same surface. Build the overlay/config model once, or they fork.
- **#2 de-risks #1.** A cleaned, opinionated desktop is where onboarding lands. Doing it first keeps onboarding from building on a surface that is about to change.

## To think about

- **Per-agent resource monitoring.** Captured agents occasionally spawn CPU/IO-heavy work (e.g. a `find` from `$HOME`); explore surfacing per-run resource consumption (CPU/mem/IO), a natural fit for the `RunManager` seam.
- **Bounded shared-proxy pool (HQ5 headroom) — nice to have, circle back.** Canvas runs now share one `mitmdump` subprocess (Tier 2, shipped); the load harness shows one subprocess hits the CPU knee around ~50 concurrent *active* streams (not open panes). The fallback is K shared subprocesses — `SharedProxyManager` generalized 1→K with **K=1 as a byte-for-byte identity default** so it ships dark and flips on via `shared_proxy_pool_size`. Buys CPU headroom + crash-isolation (a member crash hits ~runs/K, not all). **Not the focus now** — realistic single-user load won't stream 50 panes at once — but the design is execution-ready: ~4 engineer-days / ~650 LoC / medium risk, 3 PRs, change concentrated in `manager.py` (per-member subprocess/control/core/addon reused unchanged). Spec: `~/.mdx/projects/tm-tier2-bounded-pool-design.md`.
