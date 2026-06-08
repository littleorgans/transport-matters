# Slice 4 removal map

## Delete

- `api/src/transport_matters/session/timeline.py`
  - `sha256` import. The only caller is the virtual sidechain id hash.
  - `project_timeline` inline `is_sidechain` grouping and skip branch. Slice 4 materializes subagents as child sessions, so inline sidechain rows should not be projected as virtual targets.
  - `_append_virtual_sidechains`. The `subagent-sidechain:*` synthetic projection is deleted.
  - `_sidechain_root_id`. It only supports `_append_virtual_sidechains`.
- `api/src/transport_matters/session/timeline_models.py`
  - `SubagentMode` alias.
  - `mode` fields on `SubagentRef` and `SubagentSummary`.
- Tests that assert virtual sidechain projection or mode fields.

## Keep

- `api/src/transport_matters/session/timeline.py`
  - `_append_child_subagents`. This is the canonical projector path for first class subagent sessions.
  - `_child_subagent_ref`, with `subagent_id = subagent-session:<child_session_id>`.
  - child session visibility helpers and immutable message replacement helpers.
- `api/src/transport_matters/session/dao.py`
  - child session listing and owner scoped raw event reads.
- `api/src/transport_matters/session/models.py`
  - `parent_session_id` and `forked_at_seq` on `SessionRow`.
  - `ChildSessionRow` first and last seq projection.
- Transcript ingest and backfill paths, extended rather than duplicated, so both providers can discover separate subagent recordings and write child session rows.
