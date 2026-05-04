# Transport Matters — TLDR

Context control plane for coding agents. Proxies Claude Code and Codex, captures every turn, curates the payload through a deterministic pipeline, and can pause the next outbound request for inspection or editing.

No system proxy toggle. No global cert install. No sudo.

## Run it

```bash
uv tool install transport-matters
transport-matters claude                 # proxy + Claude Code in cwd
transport-matters codex ~/my-project     # proxy + Codex in a specific dir
transport-matters claude --no-claude     # proxy only, bring your own client
```

Prints the proxy URL, web UI URL, and resolved workspace CWD on launch.

## What you get

- Every turn captured to `~/.transport-matters/workspaces/{slug}/{hash}/` (original request, IR, curated request, audit metadata, transport diagnostics)
- Deterministic curation rules (strip tools, truncate system parts, rewrite descriptions, drop thinking blocks)
- Web UI with intercept list, schema-aware request editor, breakpoint arm and release, transport diagnostics, workspace history

## How it wires up

- **Claude**: reverse proxy, `ANTHROPIC_BASE_URL` -> mitmproxy -> `api.anthropic.com`
- **Codex**: explicit HTTPS proxy, `HTTPS_PROXY` + process scoped `CODEX_CA_CERTIFICATE` for Codex itself, plus Codex managed proxy marking and shell env filtering for Codex spawned commands -> mitmproxy -> `chatgpt.com/backend-api/codex/responses`

## Repo map

- `api/` — Python backend (FastAPI, mitmproxy addons, pipeline, storage). Ships as PyPI `transport-matters`.
- `www/` — React 19 + Vite 8 + Tailwind v4 web UI.
- `DOCS/` — design notes.
- `justfile` — root tasks, delegates to `api/` and `www/`.

## Dev

```bash
just install
just tool-install-editable              # global transport-matters backed by this checkout
just dev claude /path/to/workspace      # split proxy + www
just test && just check
```

See `PROJECT.md` for architecture, conventions, and the full command surface.
