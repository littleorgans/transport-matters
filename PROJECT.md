# Manicure

> **mani**fest + **cur**at**e**. Care for the cargo your coding agent carries.

Manicure is a provider-neutral context control plane for coding agents. It sits between your agent and the upstream provider, captures every turn, normalises payloads into an internal representation, runs them through a deterministic curation pipeline, and optionally pauses at a breakpoint so you can inspect or edit the next outbound request before it forwards upstream.

## What it is

Coding agents ship large, opaque payloads on every turn. A single Claude Code session routinely sends 285 KB of context: 147 tool definitions, multiple system parts, message turns. Tools alone account for two thirds of that. Manicure makes those payloads visible, editable, and reproducible.

No system proxy toggle. No global certificate install. No sudo.

## Supported agents

- **Claude Code** via a reverse proxy in front of `api.anthropic.com` (`ANTHROPIC_BASE_URL` override)
- **Codex** via an explicit HTTPS proxy for ChatGPT authenticated websocket traffic (`HTTPS_PROXY` + process scoped `CODEX_CA_CERTIFICATE`)

For Codex, Manicure snapshots the active Python trust roots, appends `~/.mitmproxy/mitmproxy-ca-cert.pem`, and passes the merged CA bundle only to the managed Codex process. The system keychain is never touched.

## Repository layout

| Path | Purpose |
| --- | --- |
| `api/` | Python backend. FastAPI server, mitmproxy addons, curation pipeline, storage, breakpoint controller. Published as the `manicure` PyPI package. |
| `www/` | React 19 + Vite 8 + Tailwind v4 web UI. Intercept list, request editor, transport diagnostics. |
| `DOCS/` | Internal design notes: cache, codex seam audit, transport artifacts, mitmproxy integration, release process. |
| `scripts/` | Local dev orchestration (`local-dev-mode.sh`). |
| `justfile` | Root task runner. Proxies into `api/` and `www/` justfiles. |
| `Procfile` | Concurrent `proxy` + `www` processes for split dev mode. |
| `release.sh` | Annotated tag + push entry point. CI publishes to PyPI. |
| `install.sh` | Bootstrap installer used by the GitHub Releases one-liner. |

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

### Inside the proxy

1. Parse provider traffic into internal request IR
2. Run deterministic curation rules (strip tools, truncate system parts, rewrite descriptions, drop thinking blocks)
3. Optionally pause at a breakpoint for manual editing
4. Serialize the curated request back to provider wire format
5. Persist exchange artifacts and transport diagnostics under `~/.manicure/workspaces/{slug}/{hash}/...`
6. Serve a local FastAPI API and React UI for inspection and control

### Backend import DAG

```text
ir -> adapters -> rules -> pipeline -> storage -> breakpoint -> server
```

`ir.py` imports nothing from `manicure`. IR models are frozen; pipeline actions return new instances rather than mutating.

## Captured artifacts

Every turn persists a workspace scoped bundle containing:

- the original outbound request
- the parsed internal representation
- the curated outbound request after rules and edits
- audit metadata for the curation pipeline
- transport level diagnostics (especially useful for Codex websocket turns)

Workspace identity is derived from the canonical target path, not the visible slug, so runs across symlinks and worktrees resolve to the same workspace.

## Web UI

Served on a kernel allocated free port alongside the proxy. Provides:

- Intercept list scoped to the current run by default
- Request editor with breakpoint arm and release controls
- Transport diagnostics view for Codex websocket turns
- Workspace history toggle for prior runs

## Install

End user:

```bash
curl -fsSL https://github.com/srobinson/manicure/releases/latest/download/install.sh | bash
# or
uv tool install manicure
```

Contributor (editable checkout as a global tool):

```bash
just install
just tool-install-editable
```

Verify:

```bash
manicure doctor
```

## Commands

Primary:

- `manicure claude [DIRECTORY] [-- passthrough...]`
- `manicure codex  [DIRECTORY] [-- passthrough...]`
- `manicure doctor`
- `manicure paths`
- `manicure list`
- `manicure version`

Everything after `--` is forwarded verbatim to the managed child process.

Useful flags: `--proxy-port`, `--web-port`, `--storage-dir`, `--print-command`, `--debug`, `--no-claude` (on `claude`), `--no-codex` (on `codex`).

## Development

From the repo root:

```bash
just start                          # uv run --project api manicure start
just dev claude /path/to/workspace  # split proxy + www via Procfile
just test                           # www + api
just check                          # lint/type across both
just build                          # www + api
```

The root `justfile` exports `TRANSPORT_MATTERS_CWD` for split dev so the proxy and API report the real target workspace rather than the checkout.

### Backend conventions (see `api/CLAUDE.md`)

- Async at I/O boundaries (hooks, routes, storage). Sync for pure computation (pipeline actions, rule matching, adapter parsing).
- Builtin type hints only: `list[str]`, `dict[str, Any]`, `X | None`. All return types annotated. `Any` requires a comment.
- Pydantic v2 idioms: `model_config = ConfigDict(...)`, `model_validate`, `model_dump(mode="json")`. IR models `frozen=True`.
- Runtime dispatch uses ABC; shape-only contracts use Protocol.
- Unit tests colocated next to source; integration tests under `tests/integration/`.
- Domain exceptions in `exceptions.py`, translated at the FastAPI layer. Always chain with `raise X from original`.

### Frontend conventions

- Vite 8 (Rolldown), React 19, TypeScript strict, Tailwind v4, Biome for lint + format, Vitest + Playwright, Lefthook for git hooks.
- Features own their components, hooks, and tests under `www/src/features/`. Cross-feature code lives in `www/src/shared/`. Features never import from other features.

## Release

```bash
just release              # interactive
just release --dry-run    # preview
just release --yes        # skip confirm
```

`release.sh` creates an annotated tag `vX.Y.Z` and pushes it. CI publishes the wheel to PyPI.

## License

Apache 2.0.
