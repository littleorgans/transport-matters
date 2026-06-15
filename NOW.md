# NOW

What we are working on next. This doc grounds focus. When scope drifts, this is the anchor.

## In flight — ephemeral `.agent-runtimes` homes (Slice 3 merged → Slice 4 next, gated on B6 step 2)

Launch Claude/Codex from a **pristine `.agent-runtimes/<name>` template** into a TM-owned **per-run ephemeral home**: template never mutated, auth injected from native `~/.claude`/`~/.codex`, durable history in Postgres (home is disposable). Spec (dual-clean): `~/.mdx/projects/agent-runtimes-ephemeral-home-spec.md`.

- **Slice 1 — PR #118** (`feat/runtime-home-slice1`, gate green, **owner-roadtested ✓**): unify the launch path onto one overlay+seed helper, add `RuntimeHomePlan`, route `run_codex` through it, **source auth from native as fallback** (fixed the desktop/canvas-pane Codex re-auth bug — verified: `tm desktop` → spawn Codex against a pristine template → `auth.json` carried over, auth works), bind descriptor/tailer/rollout to the runtime home, make `projects/`/`sessions/` local. **Merged** (`044556b`, 2026-06-15, dual-clean MoE review + owner roadtest). Follow-up fix seeds captured Codex sessions into the runtime home — they had been landing in the template's `sessions/`, so `codex resume` from a desktop pane failed with "No saved session found".
- **Slice 2 — PR #119** (`feat/runtime-home-slice2`, dual-clean MoE review): split `content_source` / `auth_source` / `hook_trust_source` in the overlay+seeder, symlink rotating credentials from native auth (Claude `.credentials.json`, Codex `auth.json`) instead of copying content, pin content config reads to the template, repoint Codex hook trust at the runtime home. macOS Claude auth owner-verified; Linux `.credentials.json` symlink covered by automated test. **Merged** (`da57a2a`, 2026-06-15).
- **Slice 3 — PR #121** (`feat/runtime-home-slice3`, "enforce template runtime home materialization", dual-clean MoE review): TEMPLATE-mode materialization with the config secret scan, native credential symlinks, missing-template-root hard-fail, and the writer audit in `PROJECT.md`. Per owner decision the allow-list **no longer fails on unknown entries** — unknowns default to symlink-include, `runtime.toml`/`.git` on the explicit ignore set, local-writable paths kept local. Allow-list is on probation; the moment it costs a debugging session it gets nuked. `rmtree` teardown stays deferred (this PR is its evidence gate). **Merged** (`9065950`, 2026-06-15). MoE earned its keep: the Codex reviewer caught a secret-scan Blocker (`OPENAI_API_KEY` slipped an exact-match scan) the Claude pass missed.
- **Slice 4 — next, gated**: `.agent-runtimes` registry seam + desktop request plumbing — thread a resolved `runtime_template` ref through the request so template mode is actually launchable (today nothing constructs a `RuntimeTemplateRef`). Targets the post-B6 `/v1` `CreateRunRequest` shape, so **sequenced after owner completes B6 step 2**. The registry resolves a dual-target template (one dir holds both Claude and Codex config) and strips generator-internal `runtime.toml`; cross-client files are harmless (Claude ignores Codex-domain files and vice versa).
- Feeds track #2 (tm owns the launch config) and the agent-runtimes initiative. Coordinated with the B6 curated `/v1` API workstream (shared launch-field carrier owned here; B6 continuation depends on Slice 1's descriptor binding). Runtimes now live at the permanent home `~/.agent-runtimes/runtimes`.

Three tracks, no committed order yet. Fork/share/eval are the destination, not this phase.

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

## 3. Session transcripts (read surface)

Browse and read past sessions. Non-interactive.

- **import**: persist the CLI's own recorded transcript stream into the DB.
- **search**: query across stored transcripts.
- **browse + view**: list sessions, open one, render the turns as a clean chat UI.
- Transcript = exactly what the CLI wrote, as persisted. Not the wire. One stream for now.
- Not in this track: replay, fork, share, eval. Deferred, not dropped. This read surface is the floor they build on.

## Couplings to respect

- **#1 and #2 share a config model.** "Options tm manages in the desktop" (#2) and "ENV & settings → edit overlays" (#1) are the same surface. Build the overlay/config model once, or they fork.
- **#2 de-risks #1.** A cleaned, opinionated desktop is where onboarding lands. Doing it first keeps onboarding from building on a surface that is about to change.
