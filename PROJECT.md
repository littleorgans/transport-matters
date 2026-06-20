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

Desktop launch can run `stable` and `preview` channels side by side. The channel
id selects the home, Postgres database, ports, Electron identity, and in window
badge from one package owned spec.

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

## Runtime home template materialization

Template mode is the only mode with explicit top level materialization policy.
Native and manual overlays keep the existing catch all symlink behavior.
Proxy only launches do not materialize a home.

Template content is read only. Known content lists remain explicit, but unknown
top level entries default to symlink include so dual target templates work
without per client rejection:

- Claude content: `CLAUDE.md`, `agents`, `commands`, `hooks`,
  `output-styles`, `plugins`, `skills`, `statusline-command.sh`.
- Codex content: `AGENTS.md`, `developer_instructions`, `hooks`,
  `hooks.json`, `plugins`, `skills`, `vendor_imports`.

Template credentials are rejected at launch. Claude rejects `.credentials.json`
and `.claude.json` with `oauthAccount` or `userID`. Codex rejects `auth.json`
and auth shaped material in `config.toml`. Generator internal files in the
explicit ignore list are excluded from the runtime home: `.git` and
`runtime.toml`. Unknown top level entries are included as symlinks, not rejected
or silently dropped.

Transport Matters home writers are:

- `materialize_runtime_home_overlay` and
  `materialize_runtime_home_template_overlay`, which create the runtime home,
  symlink content, copy local config, and link native credential files.
- `ClaudeSeeder.seed`, which writes runtime `.claude.json`.
- `_ensure_claude_skip_dangerous_prompt`, which writes runtime `settings.json`.
- `apply_claude_proxy_env_settings`, which writes runtime `settings.json`
  proxy env for the live run.
- `CodexSeeder.seed`, which writes runtime `config.toml`.
- `_relocate_codex_hook_trust_state`, which rewrites copied Codex hook trust
  keys from template paths to runtime home paths.
- `_merge_codex_project_trust`, which writes the current cwd trust stanza to
  runtime `config.toml`.
- `seed_codex_session`, reached through `CodexLaunchProfile.prepare`, which
  creates the owned rollout under runtime `sessions/`.

Known Claude writable paths are local to the runtime home: `.claude.json`,
`settings.json`, `projects`, `daemon`, `daemon.lock`, `daemon.log`,
`daemon.status.json`, `jobs`, `cache`, `downloads`, `file-history`,
`history.jsonl`, `mcp-needs-auth-cache.json`, `paste-cache`, `session-env`,
`sessions`, `shell-snapshots`, and `stats-cache.json`. `.credentials.json` is a
native auth link, never template content.

Known Codex writable paths are local to the runtime home: `config.toml`,
`sessions`, `history.jsonl`, `session_index.jsonl`, `cache`, `log`, `tmp`,
`.tmp`, `shell_snapshots`, `archived_sessions`, `computer-use`,
`process_manager`, `node_repl`, `generated_images`, `ambient-suggestions`,
`sqlite`, `goals_1.sqlite*`, `logs_2.sqlite*`, `memories_1.sqlite*`,
`state_5.sqlite*`, `internal_storage.json`, `installation_id`,
`.codex-global-state.json*`, `models_cache.json`, and `version.json`.
`auth.json` is a native auth link, never template content.

MCP and tool state written during a template run must land in an external
service, a native credential link, or the local runtime home. A template may
provide static MCP or tool configuration through known content names, unknown
symlinked content, or copied local config. Persistent MCP caches, SQLite stores,
generated files, and hook trust updates must not write to the template tree.

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
