# NOW

What we are working on next. This doc grounds focus. When scope drifts, this is the anchor.

## In flight — ephemeral `.agent-runtimes` homes (Slice 3 merged → Slice 4 next, now UNBLOCKED: B6 step 2 / runs family merged #123)

Launch Claude/Codex from a **pristine `.agent-runtimes/<name>` template** into a TM-owned **per-run ephemeral home**: template never mutated, auth injected from native `~/.claude`/`~/.codex`, durable history in Postgres (home is disposable). Spec (dual-clean): `~/.mdx/projects/agent-runtimes-ephemeral-home-spec.md`.

- **Slice 1 — PR #118** (`feat/runtime-home-slice1`, gate green, **owner-roadtested ✓**): unify the launch path onto one overlay+seed helper, add `RuntimeHomePlan`, route `run_codex` through it, **source auth from native as fallback** (fixed the desktop/canvas-pane Codex re-auth bug — verified: `tm desktop` → spawn Codex against a pristine template → `auth.json` carried over, auth works), bind descriptor/tailer/rollout to the runtime home, make `projects/`/`sessions/` local. **Merged** (`044556b`, 2026-06-15, dual-clean MoE review + owner roadtest). Follow-up fix seeds captured Codex sessions into the runtime home — they had been landing in the template's `sessions/`, so `codex resume` from a desktop pane failed with "No saved session found".
- **Slice 2 — PR #119** (`feat/runtime-home-slice2`, dual-clean MoE review): split `content_source` / `auth_source` / `hook_trust_source` in the overlay+seeder, symlink rotating credentials from native auth (Claude `.credentials.json`, Codex `auth.json`) instead of copying content, pin content config reads to the template, repoint Codex hook trust at the runtime home. macOS Claude auth owner-verified; Linux `.credentials.json` symlink covered by automated test. **Merged** (`da57a2a`, 2026-06-15).
- **Slice 3 — PR #121** (`feat/runtime-home-slice3`, "enforce template runtime home materialization", dual-clean MoE review): TEMPLATE-mode materialization with the config secret scan, native credential symlinks, missing-template-root hard-fail, and the writer audit in `PROJECT.md`. Per owner decision the allow-list **no longer fails on unknown entries** — unknowns default to symlink-include, `runtime.toml`/`.git` on the explicit ignore set, local-writable paths kept local. Allow-list is on probation; the moment it costs a debugging session it gets nuked. `rmtree` teardown stays deferred (this PR is its evidence gate). **Merged** (`9065950`, 2026-06-15). MoE earned its keep: the Codex reviewer caught a secret-scan Blocker (`OPENAI_API_KEY` slipped an exact-match scan) the Claude pass missed.
- **Slice 4 — next, gated**: `.agent-runtimes` registry seam + desktop request plumbing — thread a resolved `runtime_template` ref through the request so template mode is actually launchable (today nothing constructs a `RuntimeTemplateRef`). Targets the post-B6 `/v1` `CreateRunRequest` shape; B6 step 2 (runs family) **merged #123, so now unblocked**. The registry resolves a dual-target template (one dir holds both Claude and Codex config) and strips generator-internal `runtime.toml`; cross-client files are harmless (Claude ignores Codex-domain files and vice versa).
- Feeds track #2 (tm owns the launch config) and the agent-runtimes initiative. Coordinated with the B6 curated `/v1` API workstream (shared launch-field carrier owned here; B6 continuation depends on Slice 1's descriptor binding). Runtimes now live at the permanent home `~/.agent-runtimes/runtimes`.

Three tracks, no committed order yet. Fork/share/eval are the destination, not this phase.

## Ready to build — B6 curated `/v1` API

The product API seam #2 and #3 sit on, and the gate the ephemeral-home Slice 4 waits on. **Design ratified** (warroom-reviewed, 0 blockers): [`NOTES/captured-canvas/b6-api-spec.md`](NOTES/captured-canvas/b6-api-spec.md). One converged `/v1` namespace replacing `/api/*` in place; curated product nouns (workspace, session, transcript, run, resource) behind the RunManager/session boundary, no internals on the wire.

- Build order: **§2 session schema** ✓ merged (#122, `7d48870`) → **runs family** ✓ merged (#123, `1bb32da`) → **sessions family** ✓ merged (#124, `7fa29d1`, also landed the track #3 transcript-chat UI) → **continuation** (`continueFromSessionId`, binds the ephemeral-home Slice 1 carrier — now delivered) is the last real B6 slice. Runs family landing also unblocked ephemeral-home Slice 4 (was gated on B6 step 2).
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

## 2. Desktop cleanup

Make the desktop opinionated. tm owns the launch config; it is not a flag passthrough.

- Stop spawning Claude in the terminal. The canvas/pane path (`prepare_captured_run` → PTY → xterm via `RunManager`) becomes the only desktop launch.
- Remove the current options and passthroughs (`transport-matters desktop --help`). tm manages and optimizes options inside the app instead of forwarding raw flags.
- Run lifecycle + curated run API land via the B6 runs family (`terminate`/`interrupt`/`detach` vocab — see *Ready to build*).

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
