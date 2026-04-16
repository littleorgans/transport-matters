# manicure

> Care for the cargo your coding agent carries.

A reverse proxy for Claude Code. It sits between your agent and `api.anthropic.com`, captures every `/v1/messages` exchange, renders it in a web UI, and optionally pauses at a breakpoint so you can edit the payload before it forwards. No cert install. No system proxy. No sudo.

---

## Install

```bash
curl -fsSL https://github.com/srobinson/manicure/releases/latest/download/install.sh | bash

# Or, if you already have uv:
uv tool install manicure
```

Verify:

```bash
manicure doctor
```

---

## Quick start

```bash
# Proxy + Claude Code in the current directory
manicure start

# In a specific working directory
manicure start ~/my-project

# Proxy only, run your own client
manicure start --no-claude
```

## Source checkout

For contributors, the default local workflow is an editable tool install.
That gives you a global `manicure` command backed by this checkout, with
`mitmdump` in the same tool environment:

```bash
just tool-install-editable
```

Then from any directory:

```bash
cd ~/some/other/project
manicure start
```

If you do not want to install a tool, run the source checkout directly:

```bash
cd ~/some/other/project
uv run --project /absolute/path/to/manicure/api manicure start
```

From the repo root, `just start` is a thin wrapper around that source
run path.

For live frontend and proxy development, use the split source workflow:

```bash
# terminal 1: from the repo root
just dev /absolute/path/to/the/project/you-want-claude-to-run-in

# or from the target project itself
just --justfile /absolute/path/to/manicure/justfile dev

# terminal 2: from the target project
ANTHROPIC_BASE_URL=http://localhost:8787 API_TIMEOUT_MS=6000000 claude --dangerously-skip-permissions
```

`just dev` starts the Vite dev server for `www/` and the mitmproxy
addon from `api/`. The recipe exports `MANICURE_CWD` to the proxy so
the API reports the real target project cwd instead of the checkout's
`api/` directory.

---

## Architecture

```
client
  └─ ANTHROPIC_BASE_URL=http://localhost:{proxy_port}
        │
        ▼
   mitmproxy (reverse proxy → api.anthropic.com)
        │
        ├─ ProviderAdapter       parse raw body → InternalRequest IR
        ├─ Breakpoint            optional pause for manual editing
        ├─ OverrideStore         apply session-scoped overrides
        └─ ProviderAdapter       serialise IR → raw body → forward
        │
        ▼
   FastAPI (localhost:{web_port})   live log, breakpoint control, overrides CRUD
        │
        ▼
   React SPA                        log viewer, schema-aware editor
```
---

### Stack

| Layer | Choice |
|---|---|
| Proxy | mitmproxy, reverse proxy mode |
| Backend | FastAPI + uvicorn, embedded in mitmproxy's asyncio loop |
| Storage | `StorageBackend` ABC, `DiskStorageBackend` default |
| Frontend | Vite + React |

---

## License

Apache 2.0
