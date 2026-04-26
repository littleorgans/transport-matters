# ALP-2005 Subagent Continuation Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route fan-out subagent continuation turns back to the child track that emitted the referenced tool_use id.

**Architecture:** Extend `RunTrackState` with a small map from emitted `tool_use.id` to owning `track_id`. `TrackManager.observe_response()` records every response tool_use owner. `_resolve_tool_results()` keeps parent-side spawn and wait resolution first, then uses the owner map for child continuation routing before `_assign_request()` reaches ambiguous signature matching.

**Tech Stack:** Python, pytest, dataclasses, manicure IR objects.

---

### Task 1: Add failing regression tests

**Files:**
- Modify: `api/src/manicure/test_track_manager.py`

- [ ] Add `test_anthropic_fan_out_continuation_routes_to_correct_subagent`.
- [ ] Add `test_codex_fan_out_continuation_routes_to_correct_subagent`.
- [ ] Add `test_continuation_does_not_collide_with_parent_tool_results`.
- [ ] Run focused tests and confirm the two fan-out continuation tests fail by routing to the parent track.

### Task 2: Implement tool_use owner correlation

**Files:**
- Modify: `api/src/manicure/track_manager.py`

- [ ] Add `track_tool_uses: dict[str, str]` to `RunTrackState`.
- [ ] In `observe_response()`, record every `ToolUseBlock.id` with the current track id before handling special tool names.
- [ ] In `_resolve_tool_results()`, keep `open_spawns` and `wait_targets` behavior first.
- [ ] If no parent-side resolution applies, collect owner track ids for request tool results found in `state.track_tool_uses`.
- [ ] Return the owner when exactly one owner track is found, otherwise leave existing fallback behavior intact.

### Task 3: Verify and replay reproducer

**Files:**
- Read only: `~/.manicure/workspaces/helioy-manicure-worktrees-nancy-alp-1847/dc1dcbca/index.jsonl`

- [ ] Run `cd api && uv run pytest src/manicure/test_track_manager.py -q`.
- [ ] Run full backend checks: ruff format, ruff check, mypy, pytest.
- [ ] Replay dc1dcbca with `TrackManager` against stored request and response IR to confirm continuation entries route to subagent tracks.
- [ ] Persist session record in `~/.mdx/sessions/alp-2005-subagent-continuations.md`.
