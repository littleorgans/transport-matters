# transport-matters — architecture

Transport Matters is a context control plane for coding agents. It has two
halves that share one capture: a **live path** (proxy → capture → inspect /
breakpoint / edit) and a **retrieval layer** (a two-tier store, full-text
search, and the wire-versus-transcript diff). This document is the depth
reference for both; `TLDR.md` is the one-minute grounding and `README.md` is
the product brochure.

## System model

A coding agent is launched through the proxy (`transport-matters claude` /
`transport-matters codex`). The proxy intercepts each outbound turn, parses
the bytes into a frozen internal representation (IR), persists the raw and
parsed artifacts, optionally pauses the turn at a breakpoint for inspection
or edit, and forwards it upstream. Every captured turn is also projected into
a searchable, correlated index.

The unit of capture is a **workspace**, identified by the canonical target
path (not the visible slug), so two checkouts of one project share history. A
**run** is one launched agent process; a **turn** is one outbound request and
its response.

## Layering and the import DAG

The Python core (`api/src/transport_matters/`) has a strict acyclic
dependency order:

```
ir → adapters → rules → pipeline → storage → breakpoint → server
```

- `ir.py` imports nothing from the package; IR models are frozen.
- `canonicalization.py` is layer 1 (standard library only). It is shared by
  override audit (char accounting) and the index (block identity).
- The `index/` package (the tier-2 capture-and-retrieval substrate) sits
  **after** `storage`: it imports `ir` and `canonicalization` only, and
  `storage` must never import `index`. The index's write sink is injected at
  `load_runtime()` so there is no `storage → index` back-edge.

Module privacy is enforced: a leading underscore means private to the
defining module, and no non-test module imports a `_`-prefixed name from
another module. The rule is checked by `test_private_import_boundary.py`.

## Two streams, one block store

Two streams are captured per session and never collapsed:

- the **wire** stream — what actually reached the provider, observed by the
  proxy;
- the **transcript** stream — what the CLI recorded in its own session file.

Content is decomposed into **blocks**. A block's identity is **semantic**:
`hash = blake2b-256(identity_canonical(part))`, where `identity_canonical`
strips provider-specific noise (`provider_data`, cache hints) uniformly, so
identical content from either stream dedups to the same block. Role, stream,
section, and position live on the **edges** (`exchange_block`, `turn_block`),
never on the block and never in the hash. Lossless reconstruction is tier-1's
job, not the block's.

The **diff** is the product: for a session, `{wire_only, transcript_only,
shared}` block-id buckets. `wire_only` surfaces what the harness hides
(injected system reminders, full tool schemas, replayed context); `shared`
is the content both streams agree on, deduped to one block. The **pivot**
ranks each wire exchange against each transcript turn by shared-block
overlap.

## Tier-1: the source of truth

Per-run directory `~/.transport-matters/workspaces/{slug}/{hash}/{run}/`,
written first and never blocked by the index:

- per-exchange wire artifacts: `request.raw`, `request.ir.json`,
  `response.raw`, `response.ir.json`, the curated request, audit metadata;
- `index.jsonl` — the durable ordered list of exchanges for the run;
- `transcripts/{session_id}.jsonl` — an owned, byte-faithful snapshot of the
  consumed transcript records, so the transcript survives even if the CLI
  prunes its own file;
- `sessions.json` — the durable owned-launch facts (native session id, the
  transcript `source_descriptor` including its home directory, cli, and
  whether the id was minted).

The run manifest is a liveness beacon and is unlinked on process exit.
Durable enumeration therefore globs `*/*/*/index.jsonl`, never the manifest.

## Tier-2: the rebuildable index

A single shared SQLite database (`~/.transport-matters/index.db`, WAL),
spanning all workspaces. Tables: `session`, `wire_exchange`,
`transcript_turn`, content-addressed `block`, the `exchange_block` /
`turn_block` edges, and FTS5. It is written by one single-writer thread fed
by a DAG-safe injected post-persist sink; the wire path never blocks on, nor
fails because of, the index.

A `schema_meta` version gate guards correctness. Four keys are gated:
`schema_version`, `identity_canonical`, `session_ns`, `adapters_version`
(the last bumps on any change to a transcript adapter's normalization). When
a gated key changes, tier-2 is dropped and rebuilt from tier-1 rather than
served stale.

Read access is a two-phase FTS surface (metadata + snippet, then bodies),
timeline reconstruction per stream, the pivot and diff, and raw-byte fetch
that always reads back from tier-1. The query surface lives in
`index/queries.py` behind the `/api/index` router; raw bytes are never
copied into the database.

## Session correlation

`session_id` is both the universal correlation key and the idempotency
primary key, so the wire and transcript halves of a session converge on one
row.

- **claude** is managed-mint: the launcher mints a uuid and starts
  `claude --session-id <uuid>`, so Transport Matters owns the id by
  construction. Claude writes its transcript to a deterministic path, and the
  wire `metadata.session_id`, the transcript `sessionId`, and the filename
  stem all agree. The id is used directly as the `session_id` (`minted=True`).
- **codex** is also launcher-owned but read-back in shape: the launcher mints
  the native rollout uuid, pre-seeds the rollout, and starts
  `codex resume <uuid>`; the `session_id` is a `uuid5` synthesis over the
  owned native id (`minted=False`).

`--home-dir` redirects a managed CLI's config/session home; the resolved home
is baked into the transcript `source_descriptor` and carried explicitly, so
path resolution is faithful under a managed home. The launcher records all of
this in `sessions.json`, so the binding can be reconstructed during a cold
rebuild with no live launch environment.

## The launch and adapter ports

Two symmetric ports keep CLI specifics at the edges:

- **`LaunchProfile`** (launch side) — one per mint-capable CLI:
  `prepare` (compute the owned `source_descriptor`, seeding the transcript if
  the CLI needs one), `client_argv` (inject the owned id), and a passthrough
  guard (skip minting when the operator pinned their own session). A single
  shared `prepare_managed_session` drives every managed launch; adding a
  mint-capable CLI is one profile plus a registry entry.
- **`TranscriptAdapter`** (read side) — `bind` / `locate` / `normalize`.
  `normalize` is pure and emits only content blocks (`ir.ContentBlock`),
  which is what makes identical content dedup across streams.

## Rebuild

Tier-2 is a pure projection of tier-1. The single reusable core is
`replay_run(run_dir)`: read `sessions.json`, reconstruct each session's
binding, replay the wire stream from the raw request/response bytes, and
replay the transcript stream from the owned snapshot (never the CLI's file).
On the same content it rehashes to the same block hash, so a rebuilt index is
byte-identical to the live one, and a session survives rebuild after its CLI
transcript file is deleted.

Three thin callers share that core: `backfill` (replay one or all run dirs),
`reconcile` (replay run dirs that are missing or under-counted in tier-2,
evict tier-2 runs whose tier-1 dir is gone, skip the live set), and `rebuild`
(drop the database and replay everything). On boot, if the `schema_meta` gate
is stale, the runtime rebuilds from tier-1 under an exclusive file lock,
before the live writer opens a connection, so a derivation-logic change
repopulates the index instead of leaving it empty. Cross-process rebuild is
serialized by the lock; quiescence is ordering-based, not an epoch protocol.

## Storage and runtime contracts

- **Tier-1 first, tier-2 best-effort, off the hot path.** The proxy persists
  raw bytes before, and independently of, the index.
- **Single-writer tier-2.** One OS thread owns the database (WAL +
  `busy_timeout`); index jobs are submitted to it. Cross-thread pushes to the
  event loop go only through `loop.call_soon_threadsafe` (the broadcast layer
  is event-loop-affine; the writer is a thread).
- **Sync handlers for blocking SQLite.** FastAPI `/api/index` handlers are
  sync `def` so they run in the threadpool; only event-loop-affine work is
  `async def`.
- **Raw bytes stay in tier-1.** The database holds structure and pointers;
  raw fetch reads back from the per-run directory.

## Engineering standards

Repo-specific invariants beyond the global agent rules:

- The import DAG above has no cycles; declare new layers in `api/CLAUDE.md`.
- Block identity is semantic (`identity_canonical`), not the verbatim char
  canonicalization; role/stream/position belong on edges.
- The module privacy boundary (no cross-module `_` imports) is AST-enforced.
- Files stay at or under 700 lines; functions at or under ~150. Typing is
  builtins-only (`list[str]`, `X | None`); Pydantic v2 idioms; IR is frozen
  and pipeline actions return new instances rather than mutate.
- Domain exceptions live in `exceptions.py` and are translated at the FastAPI
  layer; always chain (`raise X from original`); never swallow silently.

The quality gate is `cd api && just ci` (format, lint, type-check, tests).
