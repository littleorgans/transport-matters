# TLDR

`transport-matters` is the wire-level observability and session history layer
for littleorgans coding agents. It proxies live agent traffic, parses the bytes
into an internal request representation, persists turn artifacts, can pause
the next outbound request so an operator can inspect or edit it before it
reaches the upstream provider, and records correlated transcript history in a
Postgres session store. No system proxy toggle, no global certificate install,
no sudo.

Two launch paths: Claude Code through a reverse proxy in front of
`api.anthropic.com`, and Codex through an explicit HTTPS proxy for the
ChatGPT authenticated websocket traffic. Proxy, FastAPI backend, and React
UI ship as one tool install rooted at `~/.transport-matters/`.

**Current focus:** see [NOW.md](./NOW.md) for what we are working on next.

## Mental Model

Transport Matters is orthogonal to the rest of the Little Organs stack. It
sees the bytes regardless of who spawned the agent and does not coordinate
with session-matters or runtime-matters at runtime.

A workspace is the unit of capture. Identity is derived from the canonical
target path, not the visible slug, so two checkouts of the same project
share history.

A turn is one outbound request and its response. Two streams are captured
and never collapsed: the **wire** (what actually hit the provider, seen by
the proxy) and the **transcript** (what the CLI recorded on disk). Their
difference is the product. The injected system reminders, tool schemas, and
replayed context the harness hides surface as wire-only content.

Storage has a durable run directory and an active session store. **Tier-1** is
the per-run source of truth under
`~/.transport-matters/workspaces/{slug}/{hash}/{run}/`: the raw request and
response bytes, plus an owned copy of the transcript and the session's launch
facts.

The active correlated store is Postgres. `SessionWriter` owns writes from the
transcript tailer and backfill paths. The API exposes owner scoped session read
surfaces and live event streaming, omitting raw bytes.

The retired legacy index, block store, diff projection, and raw fetch surface
are no longer part of the active runtime. Wire versus transcript diff remains a
product direction, but it needs the next wire store rather than the deleted diff
era substrate.

A breakpoint is the explicit pause point. Arming it in the UI holds the next
outbound turn for review or edit before release. Codex turns carry
incremental request payloads on later turns; the UI reflects that wire
reality.

A captured run can also surface inside the desktop instead of a detached CLI.
Spawning Claude into a canvas pane runs the same `transport-matters claude`
launch (reverse proxy, run directory, owned session) through a shared
`prepare_captured_run()` seam, with the PTY bridged to an xterm pane rather
than the local terminal. A server-managed `RunManager` owns the run on
`app.state`: panes spawn, list, stop, and attach over `/runs` and
`WS /runs/{id}/terminal`. Attaching replays the scrollback ring. Closing a pane stops its run (the canvas
close affordance issues `DELETE /runs/{id}`, freeing PTY, proxy, and port);
minimizing to the dock only detaches the viewer, so the run survives and restore
reattaches by run id. Runs are process-resident, so they do not outlive an API
restart.

`transport-matters doctor` is the first command when something feels wrong.

See [PROJECT.md](./PROJECT.md) for more.

## WWW workspace naming

`www/` now has three meanings during the separation work:

- `www/packages/` is the pnpm workspace source package tree.
- `www/packages/shell/` is the retired single Vite app, now a dev shell package that still emits one bundle in Phase 3.
- `api/src/transport_matters/www/` is the built browser bundle embedded in the Python package and served at `/`.
