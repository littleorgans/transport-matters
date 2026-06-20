# transport-matters

> Care for the cargo your coding agent carries.

Transport Matters is a context control plane for coding agents. It proxies live agent traffic, captures turn artifacts, shows the exchange in a web UI, and can pause the next outbound request so you can inspect or edit it before it goes upstream.

Today it supports two launch paths:
- Claude Code through a reverse proxy to `api.anthropic.com`
- Codex through an explicit HTTPS proxy for ChatGPT authenticated websocket traffic

No system proxy toggle. No global certificate install. No sudo.

## Install

```bash
curl -fsSL https://github.com/littleorgans/transport-matters/releases/latest/download/install.sh | bash

# Or, if you already have uv:
uv tool install transport-matters
```

Verify the local environment:

```bash
transport-matters doctor
```

**New here?** See **[QUICKSTART.md](./QUICKSTART.md)** for the full setup — Postgres, configuration, and first run.

## Quick start

```bash
# Proxy + Claude Code in the current directory
transport-matters claude

# Proxy + Claude Code in a specific working directory
transport-matters claude --work-dir ~/my-project

# Proxy + Codex in the current directory
transport-matters codex

# Proxy + Codex in a specific working directory
transport-matters codex --work-dir ~/my-project

# Electron canvas with local backend
transport-matters desktop --work-dir ~/my-project

# Proxy only, bring your own client
transport-matters claude --no-claude
transport-matters codex --no-codex
```

`transport-matters claude` launches a reverse proxy in front of Anthropic and points the managed Claude process at it with `ANTHROPIC_BASE_URL`.

`transport-matters codex` launches an explicit HTTPS proxy and starts Codex with:
- `HTTPS_PROXY`
- `HTTP_PROXY`
- a process scoped `CODEX_CA_CERTIFICATE`
- `CODEX_NETWORK_PROXY_ACTIVE=1`, so Codex treats the proxy vars as managed and strips them from direct shell commands
- a session scoped Codex shell environment policy that removes Transport Matters trust variables from commands Codex runs

For Codex, Transport Matters validates any user supplied CA bundle path or else snapshots the active Python trust roots, appends `~/.mitmproxy/mitmproxy-ca-cert.pem`, and passes that merged bundle only to the managed Codex process. Commands started inside Codex use their normal trust chain and are not routed through the Transport Matters proxy, including direct shell commands. No system keychain changes are required.

`transport-matters desktop` starts the local backend detached by default and
opens the Electron canvas. Use `--foreground` to stay attached,
`transport-matters tail [channel]` to read logs, and `kill <pid>` from
`transport-matters channel list` to stop a detached backend. Start Claude or
Codex from captured panes inside the desktop UI.

Standalone `claude` and `codex` launch print:
- the proxy URL
- the web UI URL
- the resolved workspace CWD

Use those exact printed endpoints. Default ports are kernel allocated free ports unless you pass `--proxy-port` or `--web-port` to the standalone command. Desktop opens the canvas directly and accepts `--web-port` for the local backend.

## Pass-through arguments

`transport-matters claude` and `transport-matters codex` own the outer CLI. Everything after `--` is passed verbatim to the managed child process.

Claude examples:

```bash
transport-matters claude -- --help
transport-matters claude -- --model sonnet --resume
transport-matters claude --work-dir ~/my-project -- -p "fix the failing test"
```

Codex examples:

```bash
transport-matters codex -- exec "fix the failing test"
transport-matters codex -- review
transport-matters codex -- login
transport-matters codex -- mcp
transport-matters codex -- app-server
```

## What you get

Every captured turn persists a run scoped artifact bundle under `~/.transport-matters/workspaces/{slug}/{hash}/{run_id}/...`. The `{slug}/{hash}/` directory is the workspace container for one CWD; each launch owns a `{run_id}/` subdirectory, so its lock, manifest, `index.jsonl`, captured exchanges, and `mitmdump.log` never collide with another run.

For Claude and Codex, Transport Matters captures:
- the original outbound request
- the parsed internal representation
- the curated outbound request after rules and edits
- audit metadata for the curation pipeline
- transport level diagnostics

In the UI you get:
- an Intercept list scoped to the current run by default
- a request editor with breakpoint release controls
- transport diagnostics for Codex websocket turns
- workspace history when you enable `Show history`

## Workflow

The normal operator flow is:

1. Start `transport-matters claude` or `transport-matters codex`
2. Let the managed client run normally
3. Arm the breakpoint in the web UI when you want to inspect the next outbound turn
4. Review or edit the request
5. Release it upstream
6. Inspect the captured artifacts if something fails

For Codex, later websocket turns carry incremental request payloads rather than replaying the full conversation on every turn. The UI reflects that wire reality.

## Multiple instances in one directory

You can run several `transport-matters claude` / `transport-matters codex` instances from the same directory at once. Each launch mints a fresh `run_id`, auto-allocates its own proxy and web ports, and gets an isolated storage root, so two instances never share a capture store, log, or breakpoint state.

- `transport-matters list` shows every live run separately, with its run id, ports, and storage dir.
- `transport-matters paths` run from *inside* a session reports that session's own paths (it reads `TRANSPORT_MATTERS_STORAGE_DIR` from the env). Run from a bare shell where several live runs share the directory, it lists them and asks you to pick one rather than guessing; pass one of the listed storage dirs back with `--workspace <storage-dir>` to select it.
- `--storage-dir` is honored verbatim. Pointing two concurrent runs at the same explicit storage dir is your responsibility; the default per-run path never collides.

Each web UI serves exactly one run. There is no aggregated view across instances yet: breakpoint state, the SSE stream, settings, and storage are all process local, so a single UI supervising several runs needs a coordinator that does not exist today. That aggregation is a deliberately separate, future workstream.

## Source checkout

For contributors, the default local workflow is an editable tool install:

```bash
just install
just install-local
```

That gives you a global `transport-matters` command backed by this checkout, with `mitmdump` in the same tool environment.

The test suite needs a local Postgres for the session store. Start it once, then run the suite:

```bash
docker compose up -d   # local Postgres on 127.0.0.1:55432
cd api && just test
```

`just test`/`just ci` default `TRANSPORT_MATTERS_TEST_DATABASE_URL` to that local Postgres; export your own to override.

Then from any target project:

```bash
cd ~/some/other/project
transport-matters claude
transport-matters codex
```

To install the latest published release instead:

```bash
just install-release
```

If you do not want a tool install, run directly from source:

```bash
cd ~/some/other/project
uv run --project /absolute/path/to/transport-matters/api transport-matters claude
uv run --project /absolute/path/to/transport-matters/api transport-matters codex
```

From the repo root:

```bash
just start
```

is a thin wrapper around:

```bash
uv run --project api transport-matters claude
```

For split frontend and proxy development:

```bash
# terminal 1, from the repo root
just dev /absolute/path/to/the/project/you-want-to-run-in
```

`just dev` starts the local backend and frontend development stack. The repo root `justfile` exports `TRANSPORT_MATTERS_CWD` so the proxy and API report the real target workspace rather than the checkout directory.

## Architecture

### Claude path

```text
Claude Code
  -> ANTHROPIC_BASE_URL=http://localhost:{proxy_port}
  -> mitmproxy reverse proxy
  -> api.anthropic.com
```

### Codex path

```text
Codex
  -> HTTPS_PROXY=http://127.0.0.1:{proxy_port}
  -> CODEX_CA_CERTIFICATE=/tmp/transport-matters-codex-ca.pem
  -> mitmproxy explicit HTTPS proxy
  -> chatgpt.com/backend-api/codex/responses
```

Inside the proxy path, Transport Matters:
- parses provider traffic into internal request IR
- runs deterministic curation rules
- optionally pauses at a breakpoint for manual editing
- serializes the curated request back to provider wire format
- persists exchange artifacts and transport diagnostics
- serves a local FastAPI and React UI for inspection and control

## Commands

Primary commands:
- `transport-matters claude`
- `transport-matters codex`
- `transport-matters desktop`
- `transport-matters tail`
- `transport-matters doctor`
- `transport-matters paths`
- `transport-matters list`
- `transport-matters version`

Useful standalone and backend flags:
- `--proxy-port`
- `--web-port`
- `--storage-dir`
- `--print-command`
- `--debug`
- `--no-claude` on `claude`
- `--no-codex` on `codex`

## Notes

- Workspace identity is derived from the canonical target path, not just the visible slug.
- Intercept defaults to the current run so live traffic is easier to read.
- Prior runs in the same workspace remain available through history.
- Codex transport is websocket based, so the raw transport view is often the fastest way to debug protocol failures.

---

See [PROJECT.md](./PROJECT.md) for more.

## License

Apache 2.0
