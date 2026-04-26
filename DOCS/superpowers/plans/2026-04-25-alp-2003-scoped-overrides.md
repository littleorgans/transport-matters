# ALP-2003 Scoped Overrides Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scope prompt overrides by `(run_id, track_id)` so edits in one parent or subagent track do not affect any other active track.

**Architecture:** ALP-2002 already classifies exchanges into tracks. ALP-2003 reuses that classification before override application, stores the resulting `TrackAssignment` in flow metadata, and applies only overrides for that track scope. The API and UI pass the current paused flow scope when reading or mutating overrides.

**Tech Stack:** FastAPI, Pydantic, mitmproxy flow metadata, pytest, React, TanStack Query, TypeScript, Vitest.

---

## Orientation

Framework and patterns confirmed:

- Backend framework: FastAPI routes under `api/src/manicure/api/v1/`.
- Override engine: pure Pydantic IR transforms in `api/src/manicure/overrides.py`.
- Override state: in process singleton from `api/src/manicure/override_state.py`, re-exported through `manicure.overrides`.
- Track classifier: in process `TrackManager` in `api/src/manicure/track_manager.py`.
- Runtime run id: `get_settings().run_id`; when absent, use the legacy root scope.
- Frontend override control path: `BreakpointEditor` -> `useOverrides` -> `www/src/api.ts`.
- Paused flow transport: backend `pause_session._paused_event_payload` -> SSE `useExchangeStream` -> `PausedFlow` in the UI store.
- No manicure-specific design docs were found in `~/.mdx/design/`.

## File Map

### Backend

- Modify `api/src/manicure/override_state.py`
  - Add `OverrideScope = tuple[str, str]` and helper functions for legacy and root fallback.
  - Store overrides as `scope -> OrderedDict[(kind, target), Override]`.
  - Store `enabled` per scope, defaulting to `True`.
  - Preserve old no-arg calls for single-track workflows.

- Modify `api/src/manicure/track_manager.py`
  - Add `classify_request(run_id, request)` for pre-response classification.
  - Keep `record_exchange` behavior by delegating to `classify_request` and then observing a response.

- Modify `api/src/manicure/request_pipeline.py`
  - Accept `run_id`.
  - Classify inbound request before applying overrides.
  - Resolve override scope from `run_id` plus `TrackAssignment.track_id`, falling back to `(run_id, run_id)` for root and legacy requests.
  - Return `(curated_ir, audit, track_assignment)`.

- Modify `api/src/manicure/flow_state.py`
  - Persist `TrackAssignment | None` in `RequestFlowState` and flow metadata.

- Modify `api/src/manicure/addon_handlers.py`
  - Pass `get_settings().run_id` into `run_pipeline`.
  - Store returned track assignment in request flow state.

- Modify `api/src/manicure/exchange_recorder.py` and `api/src/manicure/codex/exchange.py`
  - Use the stored track assignment from flow state.
  - Observe responses with that assignment instead of classifying the request a second time.
  - Fall back to existing `_assign_track` when there is no preclassified assignment.

- Modify `api/src/manicure/breakpoint.py` and `api/src/manicure/pause_session.py`
  - Add scope fields to `PausedFlow`: `run_id`, `track_id`, `parent_track_id`, `track_display_name`, `track_role`.
  - Include those fields in paused SSE events.
  - Re-audit paused previews using the paused flow scope.

- Modify `api/src/manicure/api/v1/overrides.py`
  - Add query params `run_id` and `track_id` to GET, PATCH, DELETE, and POST toggle.
  - Use scoped store calls and scoped paused preview updates.
  - Preserve no-query legacy behavior.

- Test files
  - Modify `api/src/manicure/test_override_state.py`.
  - Modify `api/src/manicure/api/v1/test_overrides.py`.
  - Add or modify request pipeline tests for track isolation.

### Frontend

- Modify `www/src/types.ts`
  - Add track fields to `IndexEntry` and `PausedFlow`.
  - Add `OverrideScope` for API calls.

- Modify `www/src/api.ts`
  - Add scope query string helpers.
  - Thread scope through override API calls.

- Modify `www/src/hooks/useOverrides.ts`
  - Accept optional scope.
  - Include scope in query keys and mutation calls.

- Modify `www/src/hooks/useExchangeStream.ts`
  - Parse track fields from paused and exchange SSE events.

- Modify `www/src/components/editor/BreakpointEditor.tsx`
  - Derive scope from `pausedFlow.run_id` and `pausedFlow.track_id`.
  - Use scoped overrides in the editor.

- Test files
  - Modify `www/src/components/editor/BreakpointEditor.test.tsx` if existing mocks assert override API calls.
  - Add focused tests for scoped API calls if an API test file exists.

## API Contract

```ts
interface OverrideScope {
  run_id?: string | null;
  track_id?: string | null;
}

// GET /api/overrides?run_id=<run>&track_id=<track>
interface OverrideListResponse {
  overrides: Override[];
  enabled: boolean;
}

// PATCH /api/overrides?run_id=<run>&track_id=<track>
interface OverrideBatchRequest {
  overrides: Override[];
}
interface OverrideMutateResponse {
  overrides: Override[];
  enabled: boolean;
  audit: OverrideAudit | null;
  curated_ir: InternalRequest | null;
}

// DELETE /api/overrides?run_id=<run>&track_id=<track>
// Returns 204.

// POST /api/overrides/toggle?run_id=<run>&track_id=<track>
interface ToggleResponse {
  enabled: boolean;
  audit: OverrideAudit | null;
  curated_ir: InternalRequest | null;
}
```

Scope resolution rules:

```python
# root fallback when run_id is known and track_id is absent
scope = (run_id, track_id or run_id)

# legacy fallback when run_id is absent
scope = ("__legacy__", track_id or "__legacy__")
```

No `Override.scope` field is added because current override kinds are request local. If a future override must apply to every track, add explicit scope semantics then.

## Tasks

### Task 1: Scoped store tests

- [ ] Add tests to `api/src/manicure/test_override_state.py`:

```python
def test_scopes_are_isolated(self) -> None:
    store = OverrideStore()
    root_override = Override(kind="tool_toggle", target="tool:bash", value=False)
    sub_override = Override(kind="tool_toggle", target="tool:bash", value=True)

    store.upsert(root_override, scope=("run-1", "run-1"))
    store.upsert(sub_override, scope=("run-1", "agent-1"))

    assert store.get_all(scope=("run-1", "run-1")) == [root_override]
    assert store.get_all(scope=("run-1", "agent-1")) == [sub_override]


def test_enabled_is_scoped(self) -> None:
    store = OverrideStore()

    store.set_enabled(False, scope=("run-1", "agent-1"))

    assert store.is_enabled(scope=("run-1", "agent-1")) is False
    assert store.is_enabled(scope=("run-1", "agent-2")) is True
```

- [ ] Run `cd api && uv run pytest src/manicure/test_override_state.py -q`.
- [ ] Confirm these tests fail because `scope`, `set_enabled`, and `is_enabled` do not exist.

### Task 2: Implement scoped store

- [ ] Update `OverrideStore` with scoped maps, helpers, and no-arg compatibility.
- [ ] Run `cd api && uv run pytest src/manicure/test_override_state.py -q` and confirm pass.

### Task 3: Track classification without double request recording

- [ ] Add `TrackManager.classify_request` and keep `record_exchange` equivalent.
- [ ] Add a unit test showing `classify_request` plus `observe_response` produces the same parent spawn state as `record_exchange`.
- [ ] Run `cd api && uv run pytest src/manicure/test_track_manager.py -q`.

### Task 4: Pipeline scoped override tests

- [ ] Add request pipeline tests with synthetic ALP-2002 fan out:
  - Parent response opens two Claude `Agent` tracks.
  - Add an override only for `agent-a`.
  - Run pipeline for `agent-a` request and assert override applies.
  - Run pipeline for `agent-b` request and assert override does not apply.
  - Repeat with two Codex subagent requests identified by metadata.
  - Assert single-track legacy calls still use no-query overrides.

- [ ] Run the new tests and confirm failure.

### Task 5: Implement pipeline and flow propagation

- [ ] Update `run_pipeline` to return the track assignment and use scoped store calls.
- [ ] Update `RequestFlowState`, `capture_request_flow_state`, `get_request_flow_state`, and `update_request_flow_state`.
- [ ] Update addon handlers and exchange persistence to reuse stored assignment and observe responses.
- [ ] Run request pipeline, track manager, exchange recorder, and Codex exchange tests.

### Task 6: API scope tests

- [ ] Add API tests in `api/src/manicure/api/v1/test_overrides.py`:
  - GET returns only the requested scope.
  - PATCH to one scope does not affect another scope.
  - DELETE clears only the requested scope.
  - Toggle affects only the requested scope.
  - Paused preview updates only when paused flow scope matches request scope.
  - Existing no-query calls still work.

- [ ] Run `cd api && uv run pytest src/manicure/api/v1/test_overrides.py -q` and confirm failure before implementation.

### Task 7: Implement API and paused scope

- [ ] Add query params to override routes.
- [ ] Add track fields to paused flow dataclass and paused SSE payloads.
- [ ] Re-audit paused previews using the matching paused flow scope.
- [ ] Run API override tests.

### Task 8: Frontend scoped override plumbing

- [ ] Add TypeScript track fields to `IndexEntry` and `PausedFlow`.
- [ ] Add `OverrideScope` and scoped API query helper.
- [ ] Update `useOverrides(scope)` query key and mutation functions.
- [ ] Update SSE parsing for track fields.
- [ ] Update `BreakpointEditor` to derive scope from `pausedFlow`.
- [ ] Run focused frontend tests, lint, and typecheck.

### Task 9: Full verification and review

- [ ] Run backend verification:

```bash
cd api
uv run ruff format --check src/
uv run ruff check src/
uv run mypy src/
uv run pytest
```

- [ ] Run frontend verification:

```bash
pnpm --dir www lint
pnpm --dir www typecheck
pnpm --dir www test
```

- [ ] Commit with a focused conventional message.
- [ ] Push branch.
- [ ] Send reviewer mail with summary, acceptance checks, and verification output.
