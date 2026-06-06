# transport-matters architecture

Transport Matters is a context control plane for coding agents. It has two
active halves that share one capture path: a live proxy path for inspect,
breakpoint, and edit; and a Postgres session store for correlated transcript
history and live session events. `TLDR.md` is the one minute grounding and
`README.md` is the product brochure.

The retired legacy index, block store, diff projection, and raw fetch surface
are no longer part of the active runtime. Wire versus transcript diff remains a
product direction, but it needs the next wire store rather than the deleted diff
era substrate.

## System model

A coding agent is launched through the proxy with `transport-matters claude` or
`transport-matters codex`. The proxy intercepts each outbound turn, parses the
bytes into a frozen internal representation, persists raw and parsed artifacts,
optionally pauses the turn at a breakpoint for inspection or edit, and forwards
it upstream.

A workspace is identified by the canonical target path, so two checkouts of one
project share history. A run is one launched agent process. A turn is one
outbound request and its response.

The transcript side is owned by the launch facts. Managed launches record the
native session id, transcript source descriptor, home directory, CLI, and
whether the id was minted. The transcript tailer follows that exact source,
copies consumed bytes into the run directory, normalizes records through the
provider adapter, and writes session events to Postgres.

## Layering and the import DAG

The Python core has a strict acyclic dependency order:

```text
ir -> adapters -> rules -> pipeline -> storage -> breakpoint -> server
```

- `ir.py` imports nothing from `transport_matters`.
- `canonicalization.py` is layer 1. It is standard library only and is shared by
  override audit character accounting.
- The `session/` package is the Postgres session store. It may import `ir`,
  `canonicalization`, surviving `index/{adapters,tailer,sessions}`, and storage
  read helpers.
- `storage` must never import `session`. Runtime sinks are injected at
  `load_runtime()` to keep the DAG clean.

Module privacy is enforced. A leading underscore means private to the defining
module, and no non test module imports a private symbol from another module.
`test_private_import_boundary.py` checks the rule.

## Two captured streams

Two streams are captured per session and never collapsed:

- the wire stream, which is what reached the provider and was observed by the
  proxy;
- the transcript stream, which is what the CLI recorded in its own session file.

The live proxy persists wire artifacts to tier 1. The transcript tailer persists
an owned transcript copy to tier 1 and emits normalized session events to
Postgres. The event stream gives the UI a durable timeline without depending on
CLI retained files.

## Tier 1 source of truth

Each run writes to
`~/.transport-matters/workspaces/{slug}/{hash}/{run}/`:

- per exchange wire artifacts: `request.raw`, `request.ir.json`,
  `response.raw`, `response.ir.json`, the curated request, and audit metadata;
- `index.jsonl`, the durable ordered list of exchanges for the run;
- `transcripts/{session_id}.jsonl`, an owned byte faithful snapshot of consumed
  transcript records;
- `sessions.json`, the durable owned launch facts.

The run manifest is a liveness beacon and is unlinked on process exit. Durable
enumeration globs `*/*/*/index.jsonl`, never the manifest.

## Session store

The active correlated store is Postgres. `SessionWriter` owns writes from the
transcript tailer and backfill paths. The API exposes owner scoped session read
surfaces and live event streaming, omitting raw bytes.

Transcript event creation is shared by live tailing and replay:

- `index/tailer.py` handles cursor state, byte offsets, record parsing, and
  adapter normalization.
- `session/ingest.py` maps raw and normalized records to event writes.
- `session/backfill.py` replays transcript snapshots from tier 1 using
  `sessions.json` and `transcripts/{session_id}.jsonl`.

The surviving `index/` package is now a compatibility namespace for transcript
adapters, tailing, and deterministic session id synthesis. It no longer owns a
database, schema, block store, query layer, rebuild gate, or raw route.

## Session correlation

`session_id` is the universal correlation key.

- Claude is managed mint. The launcher mints a uuid and starts
  `claude --session-id <uuid>`, so the wire metadata, transcript `sessionId`,
  and filename stem agree. The id is used directly with `minted=True`.
- Codex is launcher owned but read back in shape. The launcher mints the native
  rollout uuid, pre-seeds the rollout, and starts `codex resume <uuid>`. The
  stored session id is a uuid5 synthesis over the owned native id with
  `minted=False`.

`--home-dir` redirects a managed CLI's config and session home. The resolved
home is included in the transcript source descriptor and carried explicitly, so
path resolution remains faithful under managed homes.

## Launch and adapter ports

Two symmetric ports keep CLI specifics at the edges:

- `LaunchProfile`, one per mint capable CLI, prepares owned session facts,
  injects the owned id into the child argv, and respects operator pinned
  sessions.
- `TranscriptAdapter`, one per transcript provider, binds run facts to a
  session id, locates transcript sources when no owned descriptor exists, and
  normalizes raw records into provider neutral turns.

A single shared managed launch path drives current CLI profiles. Adding a new
mint capable CLI should be one profile plus one adapter.

## Backfill and replay

Session backfill is transcript only. It reads `sessions.json`, reconstructs each
session binding, replays owned transcript snapshots, and writes the same event
shape as live tailing. It does not read wire request or response bytes.

Replay is idempotent through deterministic event ids and cursor sequencing. A
snapshot write failure during live tailing prevents the cursor from advancing,
so session events never get ahead of the owned transcript copy.

## Storage and runtime contracts

- Tier 1 is authoritative. The proxy persists raw bytes before any derived
  observer work.
- Session capture startup is best effort. Failure to start the Postgres writer
  or tailer disables transcript capture for that run but does not stop the
  proxy.
- Transcript snapshots are written before session events advance.
- Public APIs do not expose raw bytes from the retired raw route. Future raw
  fetch needs an explicit wire store API.
- FastAPI routes return consistent machine readable errors through the existing
  exception translation layer.

## Engineering standards

Repo specific invariants beyond the global agent rules:

- Declare new dependency layers in `api/CLAUDE.md`.
- Keep the module privacy boundary intact.
- Files stay at or under 700 lines. Functions stay at or under roughly 150
  lines.
- Use built in generic types such as `list[str]` and `X | None`.
- Use Pydantic v2 idioms.
- IR models are frozen. Pipeline actions return new instances rather than
  mutate.
- Domain exceptions live in `exceptions.py` and are translated at the FastAPI
  layer. Always chain with `raise X from original`.

The backend quality gate is `cd api && just ci`. The frontend quality gate is
`cd www && pnpm lint && pnpm typecheck && pnpm test`.
