# manicure

> Care for the cargo your coding agent carries.

Manicure is a context control plane for coding agents. It proxies live agent traffic, captures turn artifacts, shows the exchange in a web UI, and can pause the next outbound request so you can inspect or edit it before it goes upstream.

Today it supports two launch paths:
- Claude Code through a reverse proxy to `api.anthropic.com`
- Codex through an explicit HTTPS proxy for ChatGPT authenticated websocket traffic

No system proxy toggle. No global certificate install. No sudo.

## Install

```bash
curl -fsSL https://github.com/srobinson/manicure/releases/latest/download/install.sh | bash

# Or, if you already have uv:
uv tool install manicure
```

Verify the local environment:

```bash
manicure doctor
```

## Quick start

```bash
# Proxy + Claude Code in the current directory
manicure claude

# Proxy + Claude Code in a specific working directory
manicure claude ~/my-project

# Proxy + Codex in the current directory
manicure codex

# Proxy + Codex in a specific working directory
manicure codex ~/my-project

# Proxy only, bring your own client
manicure claude --no-claude
manicure codex --no-codex
```

`manicure claude` launches a reverse proxy in front of Anthropic and points the managed Claude process at it with `ANTHROPIC_BASE_URL`.

`manicure codex` launches an explicit HTTPS proxy and starts Codex with:
- `HTTPS_PROXY`
- `HTTP_PROXY`
- a process scoped `CODEX_CA_CERTIFICATE`
- `CODEX_NETWORK_PROXY_ACTIVE=1`, so Codex treats the proxy vars as managed and strips them from direct shell commands
- a session scoped Codex shell environment policy that removes Manicure trust variables from commands Codex runs

For Codex, Manicure validates any user supplied CA bundle path or else snapshots the active Python trust roots, appends `~/.mitmproxy/mitmproxy-ca-cert.pem`, and passes that merged bundle only to the managed Codex process. Commands started inside Codex use their normal trust chain and are not routed through the Manicure proxy, including direct shell commands. No system keychain changes are required.

On launch, Manicure prints:
- the proxy URL
- the web UI URL
- the resolved workspace CWD

Use those exact printed endpoints. Default ports are kernel allocated free ports unless you pass `--proxy-port` or `--web-port`.

## Pass-through arguments

`manicure claude` and `manicure codex` own the outer CLI. Everything after `--` is passed verbatim to the managed child process.

Claude examples:

```bash
manicure claude . -- --help
manicure claude . -- --model sonnet --resume
manicure claude ~/my-project -- -p "fix the failing test"
```

Codex examples:

```bash
manicure codex . -- exec "fix the failing test"
manicure codex . -- review
manicure codex . -- login
manicure codex . -- mcp
manicure codex . -- app-server
```

For Codex, pass an explicit working directory such as `.` before `--` when the first pass-through token is a bare command like `exec`, `review`, or `login`. That keeps it from being parsed as the optional `[DIRECTORY]` argument on the outer `manicure codex` command.

## What you get

Every captured turn persists a workspace scoped artifact bundle under `~/.manicure/workspaces/{slug}/{hash}/...`.

For Claude and Codex, Manicure captures:
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

1. Start `manicure claude` or `manicure codex`
2. Let the managed client run normally
3. Arm the breakpoint in the web UI when you want to inspect the next outbound turn
4. Review or edit the request
5. Release it upstream
6. Inspect the captured artifacts if something fails

For Codex, later websocket turns carry incremental request payloads rather than replaying the full conversation on every turn. The UI reflects that wire reality.

## Source checkout

For contributors, the default local workflow is an editable tool install:

```bash
just install
just tool-install-editable
```

That gives you a global `manicure` command backed by this checkout, with `mitmdump` in the same tool environment.

Then from any target project:

```bash
cd ~/some/other/project
manicure claude
manicure codex
```

If you do not want a tool install, run directly from source:

```bash
cd ~/some/other/project
uv run --project /absolute/path/to/manicure/api manicure claude
uv run --project /absolute/path/to/manicure/api manicure codex
```

From the repo root:

```bash
just start
```

is a thin wrapper around:

```bash
uv run --project api manicure claude
```

For split frontend and proxy development:

```bash
# terminal 1, from the repo root
just dev /absolute/path/to/the/project/you-want-to-run-in
```

`just dev` starts the local backend and frontend development stack. The repo root `justfile` exports `MANICURE_CWD` so the proxy and API report the real target workspace rather than the checkout directory.

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
  -> CODEX_CA_CERTIFICATE=/tmp/manicure-codex-ca.pem
  -> mitmproxy explicit HTTPS proxy
  -> chatgpt.com/backend-api/codex/responses
```

Inside the proxy path, Manicure:
- parses provider traffic into internal request IR
- runs deterministic curation rules
- optionally pauses at a breakpoint for manual editing
- serializes the curated request back to provider wire format
- persists exchange artifacts and transport diagnostics
- serves a local FastAPI and React UI for inspection and control

## Commands

Primary commands:
- `manicure claude`
- `manicure codex`
- `manicure doctor`
- `manicure paths`
- `manicure list`
- `manicure version`

Useful flags:
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

## License

Apache 2.0
