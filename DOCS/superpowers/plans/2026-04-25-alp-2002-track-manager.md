# ALP-2002 Track Manager Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Tag every persisted exchange with a stable `track_id` and related subagent track metadata during ingest.

**Architecture:** Add a pure `transport_matters.track_manager` state machine keyed by `run_id`. Recorders classify the request before persistence, then observe the response to register or close child tracks. Storage persists track fields on `IndexEntry`; old entries load with `track_id = run_id` when `run_id` exists.

**Tech Stack:** Python 3.12, Pydantic models, pytest, existing disk storage JSONL persistence.

---

## Vertical slice orientation

- ALP-2001 is complete and reviewer approved at `4c1f1d2`.
- ALP-2002 blocks ALP-2003 and ALP-2004.
- Files to create or modify:
  - Create `api/src/transport_matters/track_manager.py` for the pure state machine.
  - Create `api/src/transport_matters/test_track_manager.py` for reference trace and synthetic unit tests.
  - Modify `api/src/transport_matters/storage/base.py` to add persisted track fields.
  - Modify `api/src/transport_matters/exchange_recorder.py` and `api/src/transport_matters/codex/exchange.py` to classify and persist track metadata.
  - Modify `api/src/transport_matters/codex/exchange_derivation.py` only if provisional rewrite events need track metadata in SSE payloads.
- Root track decision: use `track_id = run_id` for root entries. This matches the migration text in ALP-2002 and gives ALP-2003 a concrete `(run_id, track_id)` key.
- Acceptance tests:
  - Claude reference trace has root plus `toolu_01MiLL7GyXKvFTneZmojAazu`, with five subagent turns.
  - Codex reference trace has root plus `019dc432-c4bc-75d2-a8e5-be095061139d`, display name `Lagrange`; failed spawn results with no `agent_id` do not create tracks.
  - Synthetic tests cover two concurrent subagents and one level of nesting.

## Tasks

### Task 1: Failing track manager tests

- [ ] Add `api/src/transport_matters/test_track_manager.py` with helpers for synthetic IR and reference trace loaders.
- [ ] Assert the public API:
  - `TrackManager().record_exchange(run_id, request_ir, response_ir)` returns an assignment with `track_id`, `parent_track_id`, `track_role`, and `track_display_name`.
  - `TrackManager().tracks(run_id)` returns track records by track id.
- [ ] Run `cd api && uv run pytest src/transport_matters/test_track_manager.py -v`; expected failure is missing `transport_matters.track_manager`.

### Task 2: Minimal pure state machine

- [ ] Implement `api/src/transport_matters/track_manager.py` with no disk or network I/O.
- [ ] Support Claude `Agent`, Codex `spawn_agent`, Codex `wait_agent`, Codex `agent_kill`, failed Codex spawn results, fan out, and nesting.
- [ ] Run `cd api && uv run pytest src/transport_matters/test_track_manager.py -v`; expected pass.

### Task 3: Persist track fields

- [ ] Add `track_id`, `parent_track_id`, `track_display_name`, and `track_role` to `IndexEntry`.
- [ ] Ensure legacy rows with a `run_id` but no `track_id` read as root entries.
- [ ] Add storage regression coverage if existing disk tests do not cover sidecar or index JSON round trips for extra fields.
- [ ] Run `cd api && uv run pytest src/transport_matters/storage/test_disk.py -v`.

### Task 4: Wire ingest paths

- [ ] In normal HTTP ingest, call the track manager before building `IndexEntry`, and observe the response after parsing it.
- [ ] In Codex full exchange ingest, do the same.
- [ ] In Codex provisional ingest, classify the request once; on finalization, preserve existing track fields and only observe the final response.
- [ ] Emit track metadata in SSE exchange payloads.
- [ ] Run targeted recorder or Codex exchange tests.

### Task 5: Full verification and commit

- [ ] Run `cd api && uv run ruff format src/ && uv run ruff check src/ && uv run mypy src/ && uv run pytest src/transport_matters/test_track_manager.py src/transport_matters/storage/test_disk.py`.
- [ ] Commit on `nancy/ALP-1847`.
- [ ] Push and notify reviewer plus lead with SHA and verification.
